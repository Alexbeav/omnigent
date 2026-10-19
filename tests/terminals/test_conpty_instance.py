"""Managed Windows terminal behavior without a provider or native extension."""

from __future__ import annotations

import asyncio
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest

from omnigent.entities.session_resources import terminal_resource_view
from omnigent.inner import terminal
from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec, TerminalEnvSpec
from omnigent.terminals import conpty, conpty_instance
from omnigent.terminals.attach_target import ConPTYAttachTarget
from omnigent.terminals.conpty_screen import ConPTYScreen
from omnigent.terminals.registry import TerminalListEntry, TerminalRegistry
from omnigent.terminals.terminal_control import (
    CONTROL_FILE,
    TerminalControlError,
    TerminalControlServer,
    read_target,
    request_control,
)
from tests.terminals.test_conpty import _Driver


def _candidate(monkeypatch: pytest.MonkeyPatch, driver: _Driver) -> Mock:
    monkeypatch.setattr(terminal, "IS_WINDOWS", True)
    monkeypatch.setenv("OMNIGENT_WINDOWS_NATIVE_TERMINALS", "1")
    monkeypatch.setattr(conpty_instance, "create_os_environment", Mock())
    spawn = Mock(
        side_effect=lambda *a, **kw: conpty.ConPTYSession(
            driver, screen=ConPTYScreen(scrollback=kw["scrollback"])
        )
    )
    monkeypatch.setattr(conpty, "spawn_conpty", spawn)
    return spawn


def test_registered_windows_io_watchers_and_detach(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = _Driver()
    spawn = _candidate(monkeypatch, driver)
    registry = TerminalRegistry()
    spec = TerminalEnvSpec(
        command="fixture.exe",
        inherit_env=False,
        env={"aNtHrOpIc_ApI_KeY": "fixture-secret"},
        env_unset=["ANTHROPIC_API_KEY"],
        os_env=OSEnvSpec(cwd=str(tmp_path), sandbox=OSEnvSandboxSpec(type="none")),
    )
    instance = asyncio.run(registry.launch("conv", "codex", "main", spec))
    session = instance.attach_target.session
    baseline, activity, exited = threading.Event(), threading.Event(), threading.Event()
    private_dir = instance.private_dir
    try:
        assert isinstance(instance.attach_target, ConPTYAttachTarget)
        assert instance.socket_path is None and registry.native_panes() == []
        assert not any(key.upper() == "ANTHROPIC_API_KEY" for key in spawn.call_args.kwargs["env"])
        assert asyncio.run(registry.launch("conv", "codex", "main", spec)) is instance
        assert spawn.call_count == 1
        instance.start_idle_watcher_thread(
            on_idle=baseline.set,
            on_activity=activity.set,
            on_exit=exited.set,
            idle_threshold_s=0.02,
            poll_interval_s=0.01,
        )
        assert baseline.wait(1)
        viewer = session.subscribe(replay=False)
        wrapped = "wrapped Καλημέρα 😀 " * 12
        output = "HELLO Καλημέρα\r\n" + wrapped + "\r\nHARD"
        driver.output.put(output)
        assert viewer.read(timeout=1) == output
        assert activity.wait(1)
        captured = asyncio.run(instance.read())
        assert "HELLO Καλημέρα" in captured["screen"]
        joined = asyncio.run(instance.read(join_wrapped=True))
        assert wrapped.rstrip() + "\nHARD" in joined["screen"]
        assert wrapped.rstrip() not in captured["screen"]
        assert joined["scrollback_lines"] == captured["scrollback_lines"]
        replay = session.subscribe()
        assert replay.read(timeout=1) == output
        session.unsubscribe(replay)
        payload = "Καλημέρα 😀\nsecond line"
        assert asyncio.run(instance.send(payload, keys="Tab Enter")) == {"status": "sent"}
        assert driver.operations[-1] == payload + "\t\r"
        before = list(driver.operations)
        assert "error" in asyncio.run(instance.send("must not be written", keys="Unsupported"))
        assert driver.operations == before
        session.unsubscribe(viewer)
        assert asyncio.run(instance.is_alive()) and session.pid == driver.pid
        driver.status, driver.alive = 7, False
        assert exited.wait(1)
        assert instance.last_exit_status() == 7
        assert "HELLO Καλημέρα" in instance.last_exit_text()
        assert "HELLO Καλημέρα" in asyncio.run(instance.read())["screen"]
    finally:
        asyncio.run(registry.cleanup_conversation("conv"))
    assert registry.get("conv", "codex", "main") is None
    assert not private_dir.exists() and not session.workers_alive
    assert driver.closed


@pytest.mark.parametrize("operation", ["close", "cleanup_conversation", "shutdown"])
def test_failed_owned_close_remains_registered_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    driver = _Driver()
    _candidate(monkeypatch, driver)
    registry = TerminalRegistry()
    instance = asyncio.run(
        registry.launch(
            "conv",
            "shell",
            "main",
            TerminalEnvSpec(
                command="fixture.exe",
                inherit_env=False,
                os_env=OSEnvSpec(cwd=str(tmp_path), sandbox=OSEnvSandboxSpec(type="none")),
            ),
        )
    )
    original_terminate = driver.terminate
    terminate = Mock(side_effect=[RuntimeError("owned cleanup refused"), None])
    monkeypatch.setattr(driver, "terminate", terminate)
    try:
        if operation == "close":
            with pytest.raises(conpty.ConPTYError):
                asyncio.run(registry.close("conv", "shell", "main"))
        elif operation == "cleanup_conversation":
            asyncio.run(registry.cleanup_conversation("conv"))
        else:
            asyncio.run(registry.shutdown())
        assert registry.get("conv", "shell", "main") is instance
        assert instance.private_dir.exists() and not driver.closed
    finally:
        monkeypatch.setattr(driver, "terminate", original_terminate)
        asyncio.run(registry.close("conv", "shell", "main"))
    assert registry.get("conv", "shell", "main") is None
    assert not instance.private_dir.exists() and driver.closed


@pytest.mark.parametrize(
    "spec",
    [
        TerminalEnvSpec(os_env=OSEnvSpec(fork=True)),
        TerminalEnvSpec(os_env=OSEnvSpec(start_in_scratch=True)),
        TerminalEnvSpec(tmux_start_on_attach=True),
        TerminalEnvSpec(os_env=OSEnvSpec(sandbox=OSEnvSandboxSpec(type="linux_bwrap"))),
        TerminalEnvSpec(
            os_env=OSEnvSpec(sandbox=OSEnvSandboxSpec(type="none", egress_rules=["*.test"]))
        ),
    ],
)
def test_windows_factory_refuses_unqualified_policy_before_spawn(
    monkeypatch: pytest.MonkeyPatch,
    spec: TerminalEnvSpec,
) -> None:
    spawn = _candidate(monkeypatch, _Driver())
    with pytest.raises(ValueError, match="separately qualified"):
        terminal.create_terminal_instance("shell", "main", spec)
    spawn.assert_not_called()
    conpty_instance.create_os_environment.assert_not_called()


def test_windows_factory_stays_disabled_without_explicit_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(terminal, "IS_WINDOWS", True)
    monkeypatch.delenv("OMNIGENT_WINDOWS_NATIVE_TERMINALS", raising=False)
    with pytest.raises(RuntimeError, match="not supported on Windows"):
        terminal.create_terminal_instance("shell", "main", TerminalEnvSpec())


def test_native_resource_metadata_has_no_tmux_socket(tmp_path: Path) -> None:
    instance = conpty_instance.ConPTYTerminalInstance(
        name="shell", session_key="main", socket_path=None, private_dir=tmp_path
    )
    view = terminal_resource_view("conv", TerminalListEntry("shell", "main", instance))
    assert view.metadata["tmux_socket"] is None


def test_control_capability_is_private_and_revoked_before_failed_owned_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    driver = _Driver()
    _candidate(monkeypatch, driver)
    created = conpty_instance.create_conpty_instance(
        "claude",
        "main",
        TerminalEnvSpec(
            command="fixture.exe",
            inherit_env=False,
            os_env=OSEnvSpec(cwd=str(tmp_path), sandbox=OSEnvSandboxSpec(type="none")),
        ),
    )
    instance = created.instance
    asyncio.run(instance.launch(cwd=tmp_path))
    instance.publish_control_target(tmp_path)
    target = instance._control_server.target
    payload = terminal_resource_view("fixture", TerminalListEntry("claude", "main", instance))
    assert target.token not in str(payload) and "terminal-control" not in str(payload)
    original = driver.terminate

    def fail_after_revocation():
        with pytest.raises(TerminalControlError):
            request_control(target, "state")
        assert not (tmp_path / CONTROL_FILE).exists()
        raise RuntimeError("owned cleanup refused")

    monkeypatch.setattr(driver, "terminate", fail_after_revocation)
    try:
        with pytest.raises(conpty.ConPTYError):
            asyncio.run(instance.close())
        assert instance.private_dir.exists() and not driver.closed
    finally:
        monkeypatch.setattr(driver, "terminate", original)
        asyncio.run(instance.close())
    assert driver.closed and not instance.private_dir.exists()


@pytest.fixture
def control_instance(tmp_path):
    directory, private = tmp_path / "bridge", tmp_path / "terminal"
    directory.mkdir(mode=0o700)
    private.mkdir(mode=0o700)
    session = conpty.ConPTYSession(_Driver(), screen=ConPTYScreen())
    instance = conpty_instance.ConPTYTerminalInstance(
        name="claude", session_key="main", socket_path=None, private_dir=private
    )
    instance._session, instance.running = session, True
    try:
        yield instance, session, directory
    finally:
        asyncio.run(instance.close())
    assert not session.workers_alive


class _ObservedLifecycleLock:
    def __init__(self, events):
        self.lock = threading.Lock()
        self.events = events
        self.observe = False

    def __enter__(self):
        if self.observe:
            self.events.put("lock")
        self.lock.acquire()

    def __exit__(self, *exc):
        self.lock.release()


@pytest.mark.parametrize("contender", ["close", "publish"])
def test_control_creation_serializes_with_close_and_other_publications(
    control_instance, monkeypatch, contender
) -> None:
    instance, session, directory = control_instance
    created, release = threading.Event(), threading.Event()
    events, servers = queue.Queue(), []
    lock = _ObservedLifecycleLock(events)
    instance._control_lifecycle_lock = lock

    def paused_create(owned):
        server = TerminalControlServer(owned)
        servers.append(server)
        if len(servers) == 1:
            created.set()
            assert release.wait(5)
        else:
            events.put("extra endpoint")
        return server

    async def observe_cleanup():
        events.put("cleanup")

    monkeypatch.setattr(conpty_instance, "TerminalControlServer", paused_create)
    monkeypatch.setattr(instance, "_stop_idle_watcher", observe_cleanup)
    try:
        with ThreadPoolExecutor(2) as workers:
            publication = workers.submit(instance.publish_control_target, directory)
            try:
                assert created.wait(5)
                lock.observe = True
                if contender == "close":
                    other = workers.submit(lambda: asyncio.run(instance.close()))
                else:
                    other = workers.submit(instance.publish_control_target, directory)
                assert events.get(timeout=5) == "lock"
                assert not other.done() and len(servers) == 1
            finally:
                release.set()
            publication.result(timeout=5)
            other.result(timeout=5)
        assert instance._control_server is servers[0]
        if contender == "close":
            assert read_target(directory) is None
            assert not servers[0]._thread.is_alive() and not session.alive
            with pytest.raises(TerminalControlError):
                request_control(servers[0].target, "state")
        else:
            assert read_target(directory) == servers[0].target
            assert control_instance[1].alive and len(servers) == 1
    finally:
        release.set()
        for server in servers:
            server.close()


def test_close_state_prevents_endpoint_creation_during_session_cleanup(
    control_instance, monkeypatch
) -> None:
    instance, session, directory = control_instance
    closing, release = threading.Event(), threading.Event()
    original_close = session.close
    create = Mock(side_effect=AssertionError("endpoint created after close began"))

    def paused_close():
        closing.set()
        assert release.wait(5)
        original_close()

    monkeypatch.setattr(session, "close", paused_close)
    monkeypatch.setattr(conpty_instance, "TerminalControlServer", create)
    with ThreadPoolExecutor(2) as workers:
        cleanup = workers.submit(lambda: asyncio.run(instance.close()))
        try:
            assert closing.wait(5) and session.alive
            with pytest.raises(RuntimeError, match="closing"):
                workers.submit(instance.publish_control_target, directory).result(timeout=5)
            create.assert_not_called()
        finally:
            release.set()
        cleanup.result(timeout=5)
    assert instance._control_server is None and read_target(directory) is None
