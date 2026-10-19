"""Startup tests for Codex app server."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock

import pytest

from omnigent.errors import ErrorCode, OmnigentError
from omnigent.harnesses.codex_egress import CertificateFailure
from omnigent.harnesses.codex_native.app_server import (
    CodexAppServerClient,
    CodexNativeAppServer,
)
from omnigent.harnesses.codex_native.bridge import (
    read_certificate_failure,
    record_certificate_failure,
)
from tests.harnesses.codex_native.app_server._support import (
    _disable_codex_startup_rpc,
    _FakeStartupClient,
    _set_codex_version,
    _test_app_server,
)


@pytest.mark.parametrize("windows", [False, True])
def test_app_server_hidden_flags_preserve_process_group(
    monkeypatch: pytest.MonkeyPatch, windows: bool
) -> None:
    from omnigent.harnesses.codex_native import app_server

    monkeypatch.setattr(app_server, "IS_WINDOWS", windows)
    monkeypatch.setattr(app_server.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(app_server._proc, "spawn_kwargs", lambda: {"creationflags": 0x200})
    assert app_server._native_codex_spawn_kwargs() == {
        "creationflags": 0x08000200 if windows else 0x200
    }


@pytest.mark.parametrize("process_owner", ["posix", "windows-owned", "windows-refused"])
@pytest.mark.parametrize("existing_cap_state", [None, b"retained capability state"])
async def test_start_reuses_initialized_readiness_client_for_hook_trust(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    process_owner: str,
    existing_cap_state: bytes | None,
) -> None:
    """Startup trusts hooks over the readiness connection, then closes it."""
    from omnigent.harnesses.codex_native import app_server as codex_native_app_server

    source_home = tmp_path / "source-codex-home"
    source_home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(source_home))

    async def _supported_version(_codex_path: str) -> tuple[int, int, int]:
        if existing_cap_state is not None:
            assert cap_state.read_bytes() == existing_cap_state
        elif process_owner == "posix":
            assert not cap_state.exists()
        else:
            assert cap_state.read_bytes() == b""
        return (0, 147, 0)

    startup_client = _FakeStartupClient()
    trusted_with: list[object] = []
    job = Mock()
    containment = Mock(return_value=job if process_owner == "windows-owned" else None)
    monkeypatch.setattr(codex_native_app_server, "IS_WINDOWS", process_owner != "posix")
    monkeypatch.setattr(
        codex_native_app_server.WindowsJobObjectSandboxBackend, "post_spawn", containment
    )

    async def _ready(_self: CodexNativeAppServer) -> _FakeStartupClient:
        return startup_client

    async def _trust(
        _self: CodexNativeAppServer, *, client: CodexAppServerClient | None = None
    ) -> None:
        trusted_with.append(client)

    monkeypatch.setattr(codex_native_app_server, "_codex_cli_version", _supported_version)
    monkeypatch.setattr(CodexNativeAppServer, "_wait_until_ready", _ready)
    monkeypatch.setattr(CodexNativeAppServer, "_trust_policy_hooks", _trust)
    server = _test_app_server(
        tmp_path,
        tmp_path / "codex-home",
        tmp_path / "bridge",
        workspace,
    )
    cap_state = server.codex_home / "cap_sid"
    if existing_cap_state is not None:
        server.codex_home.mkdir(exist_ok=True)
        cap_state.write_bytes(existing_cap_state)

    if process_owner == "windows-refused":
        with pytest.raises(RuntimeError, match="ownership was not established"):
            await server.start()
        assert server.proc is None
        assert trusted_with == [] and startup_client.close_calls == 0
        return
    await server.start()
    try:
        assert trusted_with == [startup_client]
        assert startup_client.close_calls == 1
        if process_owner == "windows-owned":
            assert server._windows_process_owner is job
            containment.assert_called_once()
        else:
            containment.assert_not_called()
    finally:
        await server.close()
    if process_owner == "windows-owned":
        job.close.assert_called_once()


async def test_failed_windows_owner_close_retains_handle_for_retry(tmp_path: Path) -> None:
    server = _test_app_server(tmp_path, tmp_path / "home", tmp_path / "bridge", tmp_path)
    process, job = Mock(returncode=0), Mock()
    job.close.side_effect = [OSError("owned close failed"), None]
    server.proc = process
    server._windows_process_owner = job
    with pytest.raises(OSError, match="owned close failed"):
        await server.close()
    assert server.proc is None and server._windows_process_owner is job
    await server.close()
    assert server.proc is None and server._windows_process_owner is None
    assert job.close.call_count == 2


@pytest.mark.parametrize("cancelled", [False, True])
async def test_failed_start_drains_process_when_windows_owner_close_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancelled: bool
) -> None:
    """A failed Job close cannot hide startup failure or strand the process."""
    from omnigent.harnesses.codex_native import app_server

    server = _test_app_server(tmp_path, tmp_path / "home", tmp_path / "bridge", tmp_path)
    failure = asyncio.CancelledError() if cancelled else RuntimeError("readiness failed")
    job, owner_lock = Mock(), Mock(path=tmp_path / "owner.lock")
    job.close.side_effect = [OSError("owned close failed"), None]
    process: asyncio.subprocess.Process | None = None

    async def _fail_readiness(self: CodexNativeAppServer) -> _FakeStartupClient:
        nonlocal process
        process = self.proc
        assert process is not None and process.returncode is None
        raise failure

    _set_codex_version(monkeypatch, (0, 147, 0))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "source-home"))
    monkeypatch.setattr(app_server, "IS_WINDOWS", True)
    monkeypatch.setattr(app_server, "acquire_codex_native_process_owner_lock", lambda: owner_lock)
    monkeypatch.setattr(app_server.WindowsJobObjectSandboxBackend, "post_spawn", lambda *_: job)
    monkeypatch.setattr(
        app_server,
        "_build_native_codex_app_server_argv",
        lambda **_: [server.codex_path, "-c", "import time; time.sleep(60)"],
    )
    monkeypatch.setattr(CodexNativeAppServer, "_wait_until_ready", _fail_readiness)
    try:
        with pytest.raises(type(failure)) as caught:
            await server.start()
        assert caught.value is failure
        assert process is not None and process.returncode is not None
        assert server.proc is None and server.stderr_task is None
        assert server.process_owner_lock is None
        owner_lock.close.assert_called_once()
        assert server._windows_process_owner is job
    finally:
        await server.close()
    assert server._windows_process_owner is None
    assert job.close.call_count == 2


@pytest.mark.windows_only
def test_windows_app_server_job_closes_owned_fixture_tree(tmp_path: Path) -> None:
    from tests.harnesses.codex_native.app_server.windows_owner_probe import run_probe

    result = run_probe(tmp_path / "owned-app-server")
    assert result["status"] == "passed"
    assert result["owned_processes_remaining"] == 0


async def test_start_cancellation_closes_reused_client_and_app_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancellation during hook trust closes both startup resources."""
    from omnigent.harnesses.codex_native import app_server as codex_native_app_server

    source_home = tmp_path / "source-codex-home"
    source_home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(source_home))

    async def _supported_version(_codex_path: str) -> tuple[int, int, int]:
        return (0, 147, 0)

    startup_client = _FakeStartupClient()
    trust_started = asyncio.Event()

    async def _ready(_self: CodexNativeAppServer) -> _FakeStartupClient:
        return startup_client

    async def _trust(
        _self: CodexNativeAppServer, *, client: CodexAppServerClient | None = None
    ) -> None:
        assert client is startup_client
        trust_started.set()
        await asyncio.Future()

    monkeypatch.setattr(codex_native_app_server, "_codex_cli_version", _supported_version)
    monkeypatch.setattr(CodexNativeAppServer, "_wait_until_ready", _ready)
    monkeypatch.setattr(CodexNativeAppServer, "_trust_policy_hooks", _trust)
    server = _test_app_server(
        tmp_path,
        tmp_path / "codex-home",
        tmp_path / "bridge",
        workspace,
    )

    task = asyncio.create_task(server.start())
    await trust_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert startup_client.close_calls == 1
    assert server.proc is None
    assert server.stderr_task is None


async def test_wait_until_ready_closes_failed_client_before_reconnect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refused readiness attempt is closed before returning its retry."""
    from omnigent.harnesses.codex_native import app_server as codex_native_app_server

    @dataclass
    class _ProbeClient:
        fail_connect: bool
        connect_calls: int = 0
        close_calls: int = 0

        async def connect(self) -> None:
            self.connect_calls += 1
            if self.fail_connect:
                raise OSError("listener not ready")

        async def close(self) -> None:
            self.close_calls += 1

    first = _ProbeClient(fail_connect=True)
    second = _ProbeClient(fail_connect=False)
    attempts = [first, second]

    def _client(*_args: object, **_kwargs: object) -> _ProbeClient:
        return attempts.pop(0)

    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(codex_native_app_server, "CodexAppServerClient", _client)
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    server = _test_app_server(
        tmp_path,
        tmp_path / "codex-home",
        tmp_path / "bridge",
        workspace,
    )
    server.proc = Mock(returncode=None)

    connected = await server._wait_until_ready()

    assert connected is second
    assert first.connect_calls == 1
    assert first.close_calls == 1
    assert second.connect_calls == 1
    assert second.close_calls == 0


async def test_wait_until_ready_cancellation_closes_connecting_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancellation during initialize closes the half-open startup client."""
    from omnigent.harnesses.codex_native import app_server as codex_native_app_server

    connect_started = asyncio.Event()

    @dataclass
    class _ConnectingClient:
        close_calls: int = 0

        async def connect(self) -> None:
            connect_started.set()
            await asyncio.Future()

        async def close(self) -> None:
            self.close_calls += 1

    client = _ConnectingClient()
    monkeypatch.setattr(
        codex_native_app_server,
        "CodexAppServerClient",
        lambda *_args, **_kwargs: client,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    server = _test_app_server(
        tmp_path,
        tmp_path / "codex-home",
        tmp_path / "bridge",
        workspace,
    )
    server.proc = Mock(returncode=None)

    task = asyncio.create_task(server._wait_until_ready())
    await connect_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert client.close_calls == 1


async def test_wait_until_ready_deadline_is_the_app_server_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A listener ready after the discovery budget but inside the app-server budget succeeds."""
    from omnigent.harnesses.codex_native import app_server as codex_native_app_server

    loop = asyncio.get_running_loop()
    real_time = loop.time
    clock = {"offset": 0.0}
    monkeypatch.setattr(loop, "time", lambda: real_time() + clock["offset"])
    # Each refused probe costs 5 s of virtual time, so the listener accepts after
    # 20 s: past the 10 s discovery budget, inside the 60 s app-server budget.
    ready_at = loop.time() + 20.0

    @dataclass
    class _SlowListenerClient:
        close_calls: int = 0

        async def connect(self) -> None:
            if loop.time() < ready_at:
                clock["offset"] += 5.0
                raise OSError("[Errno 111] Connect call failed ('127.0.0.1', 57045)")

        async def close(self) -> None:
            self.close_calls += 1

    clients: list[_SlowListenerClient] = []

    def _client(*_args: object, **_kwargs: object) -> _SlowListenerClient:
        clients.append(_SlowListenerClient())
        return clients[-1]

    monkeypatch.setattr(codex_native_app_server, "CodexAppServerClient", _client)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    server = _test_app_server(
        tmp_path,
        tmp_path / "codex-home",
        tmp_path / "bridge",
        workspace,
    )
    server.listen_url = "ws://127.0.0.1:57045"
    server.proc = Mock(returncode=None)

    connected = await server._wait_until_ready()

    assert connected is clients[-1]
    assert connected.close_calls == 0
    assert all(client.close_calls == 1 for client in clients[:-1])
    assert clock["offset"] > codex_native_app_server._CONNECT_TIMEOUT_SECONDS
    assert clock["offset"] < codex_native_app_server._APP_SERVER_READY_TIMEOUT_SECONDS


@pytest.mark.parametrize("listen_url", ["ws://127.0.0.1:57045", None], ids=["ws", "unix"])
async def test_wait_until_ready_timeout_reports_listen_target_and_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, listen_url: str | None
) -> None:
    """A listener that never accepts fails after the app-server budget, naming the target."""
    from omnigent.harnesses.codex_native import app_server as codex_native_app_server

    loop = asyncio.get_running_loop()
    real_time = loop.time
    clock = {"offset": 0.0}
    monkeypatch.setattr(loop, "time", lambda: real_time() + clock["offset"])

    @dataclass
    class _RefusingClient:
        close_calls: int = 0

        async def connect(self) -> None:
            # Each refused probe costs 25 s of virtual time: three attempts
            # exhaust the 60 s budget without a real wait.
            clock["offset"] += 25.0
            raise OSError("[Errno 111] Connect call failed ('127.0.0.1', 57045)")

        async def close(self) -> None:
            self.close_calls += 1

    clients: list[_RefusingClient] = []

    def _client(*_args: object, **_kwargs: object) -> _RefusingClient:
        clients.append(_RefusingClient())
        return clients[-1]

    monkeypatch.setattr(codex_native_app_server, "CodexAppServerClient", _client)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    server = _test_app_server(
        tmp_path,
        tmp_path / "codex-home",
        tmp_path / "bridge",
        workspace,
    )
    server.listen_url = listen_url
    server.proc = Mock(returncode=None)

    with pytest.raises(RuntimeError) as excinfo:
        await server._wait_until_ready()

    message = str(excinfo.value)
    budget = codex_native_app_server._APP_SERVER_READY_TIMEOUT_SECONDS
    target = listen_url or f"unix://{server.socket_path}"
    assert message.startswith(
        f"Timed out after {budget:g}s waiting for the Codex app-server at {target}: "
    )
    assert "Connect call failed" in message
    assert (str(server.socket_path) in message) is (listen_url is None)
    assert len(clients) == 3
    assert all(client.close_calls == 1 for client in clients)


async def test_standalone_hook_trust_closes_client_when_connect_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed standalone trust handshake closes its partially-open client."""
    from omnigent.harnesses.codex_native import app_server as codex_native_app_server

    @dataclass
    class _FailingClient:
        close_calls: int = 0

        async def connect(self) -> None:
            raise RuntimeError("initialize failed")

        async def close(self) -> None:
            self.close_calls += 1

    client = _FailingClient()
    monkeypatch.setattr(
        codex_native_app_server,
        "CodexAppServerClient",
        lambda *_args, **_kwargs: client,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    server = _test_app_server(
        tmp_path,
        tmp_path / "codex-home",
        tmp_path / "bridge",
        workspace,
    )

    with pytest.raises(RuntimeError, match="initialize failed"):
        await server._trust_policy_hooks()

    assert client.close_calls == 1


async def test_start_can_delegate_global_process_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner-owned Codex startup leaves global cleanup to the host janitor."""
    real_codex_home = tmp_path / "real-codex-home"
    real_codex_home.mkdir()
    codex_home = tmp_path / "codex-home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(real_codex_home))
    _disable_codex_startup_rpc(monkeypatch)
    reconcile_calls = 0

    def _record_reconcile() -> int:
        nonlocal reconcile_calls
        reconcile_calls += 1
        return 0

    monkeypatch.setattr(
        "omnigent.harnesses.codex_native.app_server.reconcile_codex_native_process_registry",
        _record_reconcile,
    )
    server = _test_app_server(
        tmp_path,
        codex_home,
        tmp_path / "bridge",
        workspace,
    )
    server.reconcile_process_registry = False

    await server.start()
    await server.close()

    assert reconcile_calls == 0


async def test_start_clears_previous_launch_certificate_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A certificate record left by an earlier launch must not fail this launch's turns."""
    from omnigent.harnesses.codex_native import app_server as codex_native_app_server

    source_home = tmp_path / "source-codex-home"
    source_home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bridge_dir = tmp_path / "bridge"
    bridge_dir.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(source_home))

    async def _supported_version(_codex_path: str) -> tuple[int, int, int]:
        return (0, 147, 0)

    monkeypatch.setattr(codex_native_app_server, "_codex_cli_version", _supported_version)
    _disable_codex_startup_rpc(monkeypatch)
    record_certificate_failure(
        bridge_dir, CertificateFailure(evidence="certificate expired", expired=True)
    )
    server = _test_app_server(tmp_path, tmp_path / "codex-home", bridge_dir, workspace)

    await server.start()
    try:
        assert read_certificate_failure(bridge_dir) is None
    finally:
        await server.close()


async def test_start_reports_a_removed_workspace_before_any_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deleted worktree fails as WORKSPACE_MISSING instead of a bare spawn ENOENT."""
    from omnigent.harnesses.codex_native import app_server as codex_native_app_server

    source_home = tmp_path / "source-codex-home"
    source_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(source_home))

    async def _supported_version(_codex_path: str) -> tuple[int, int, int]:
        return (0, 147, 0)

    monkeypatch.setattr(codex_native_app_server, "_codex_cli_version", _supported_version)
    _disable_codex_startup_rpc(monkeypatch)
    codex_home = tmp_path / "codex-home"
    server = _test_app_server(tmp_path, codex_home, tmp_path / "bridge", tmp_path / "removed")

    with pytest.raises(OmnigentError) as failure:
        await server.start()

    assert failure.value.code == ErrorCode.WORKSPACE_MISSING
    assert server.proc is None
    assert not codex_home.exists()
