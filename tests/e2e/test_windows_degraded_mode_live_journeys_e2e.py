"""E2E reproduction: the two Windows degraded-mode defects still live on main.

On native Windows the documented degraded-mode subset (server, web UI, SDK
harnesses) breaks along a chain of defects. Three of the five reported links
are fixed on main; these tests pin the two that still reproduce, using the
smallest possible POSIX stand-in for the Windows-only platform facts:

1. ``test_host_daemon_tunnel_survives_windows_ansi_stdio`` — the background
   host daemon's "connected" success print contains glyphs (``✓`` / ``↑``)
   and runs inside the tunnel handler. A default-locale Windows console hands
   the daemon cp1252 stdio, so the print raises ``UnicodeEncodeError``, the
   success message itself tears down the freshly-established tunnel, and the
   daemon loops "Host tunnel disconnected: 'charmap' codec can't encode
   character ... Reconnecting" forever while ``omnigent run`` times out
   waiting for it. The CLI hardens its own stdio in ``main()``, but the
   daemon entry (``python -m omnigent.host._daemon_entry``) never passes
   through it. The test spawns the real daemon entry against the live e2e
   server with the daemon env built by the real production builder
   (``_build_host_daemon_env``), emulating Windows-ANSI stdio with Windows'
   own precedence rules: cp1252 streams UNLESS the daemon env carries
   ``PYTHONUTF8=1`` / ``PYTHONIOENCODING`` (so an env-default fix passes) and
   applied BEFORE the entry point runs (so a daemon-side runtime stdio
   hardening also passes, by winning afterwards).

2. ``test_os_tools_start_under_windows_config_delivery_without_sandbox`` —
   on Windows the OS-tool helper client delivers its config via a file in the
   helper's private scratch tmpdir (``--config-file``), but that tmpdir is
   only created under ``if sandbox.active:`` — and Windows never has an
   active sandbox. ``_start_locked`` asserts a precondition the platform can
   never meet, the helper can never start, and every ``sys_os_shell`` /
   ``sys_os_read`` call a session makes returns an error payload (the web
   UI's Working folder 502s for the same reason). The test drives the real
   environment factory and helper round-trip with the sandbox genuinely
   inactive (the only state Windows ever has) and only the ``IS_WINDOWS``
   flag patched in the client process; the helper subprocess imports the
   module fresh and runs the real POSIX ops, so a fixed client makes the
   whole journey complete.

Both run against the mock LLM server — no real credentials needed::

    pytest tests/e2e/test_windows_degraded_mode_live_journeys_e2e.py -v
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest
import yaml

import omnigent.inner.os_env as os_env_module
from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec
from omnigent.process_logging import PROCESS_LOG_FILE_ENV_VAR
from tests._helpers.compat import apply_runner_env, runner_executable
from tests.e2e.conftest import POLL_INTERVAL_S

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "POSIX stand-in for the Windows-only failure states; on native "
        "Windows the journeys reproduce directly without the emulation"
    ),
)

_REPO_ROOT = Path(__file__).resolve().parents[2]

# The daemon-killing failure signature: str(UnicodeEncodeError) for any glyph
# on a legacy codepage stream ("'charmap' codec can't encode character ...").
_ENCODE_CRASH_MARKER = "can't encode"

# Runs as ``python -c`` around the real daemon entry point. Recreates the
# stdio-encoding decision a default-locale Windows console makes: legacy ANSI
# (cp1252) streams unless UTF-8 mode or an explicit PYTHONIOENCODING is set.
# Applied before the entry point so a daemon that hardens its own stdio at
# startup reconfigures afterwards and wins — exactly as it would on Windows.
_WINDOWS_ANSI_STDIO_BOOTSTRAP = """\
import os, sys

if os.environ.get("PYTHONUTF8") != "1" and not os.environ.get("PYTHONIOENCODING"):
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="cp1252")

sys.argv = ["omnigent-host-daemon", "--server", sys.argv[1]]
from omnigent.host._daemon_entry import main

main()
"""


def _read_text(path: Path) -> str:
    """Read a log file leniently (it may hold cp1252 bytes), or ``""``."""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _crash_lines(*logs: str) -> list[str]:
    """Collect log lines carrying the legacy-codepage encode crash."""
    lines: list[str] = []
    for log in logs:
        lines.extend(line for line in log.splitlines() if _ENCODE_CRASH_MARKER in line)
    return lines


def _host_online(client: httpx.Client, host_id: str) -> bool:
    """Return True when *host_id* reports online via ``GET /v1/hosts``."""
    try:
        resp = client.get("/v1/hosts")
    except httpx.HTTPError:
        return False
    if resp.status_code != 200:
        return False
    return any(
        host.get("host_id") == host_id and host.get("status") == "online"
        for host in resp.json().get("hosts", [])
    )


def _terminate(proc: subprocess.Popen[bytes]) -> None:
    """SIGTERM then SIGKILL a subprocess, reaping it."""
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def test_host_daemon_tunnel_survives_windows_ansi_stdio(
    live_server: str,
    http_client: httpx.Client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The auto-spawned host daemon must keep its tunnel on legacy-ANSI stdio.

    Journey: ``omnigent run`` spawns the background daemon → the daemon
    connects and registers → the "connected" status print hits the console.
    On a cp1252 console that print must not tear down the tunnel: the host
    stays online and the daemon log never records the encode crash that
    previously drove the infinite reconnect loop and the client-side
    "connect daemon did not come online within 30s" timeout.
    """
    # Isolated identity/state under tmp: the daemon derives its config, data
    # dir, and lifecycle locks from HOME.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OMNIGENT_DATA_DIR", str(tmp_path / "omnigent-data"))
    # The user set nothing UTF-8-related — the reported default-console state.
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)

    omni_dir = tmp_path / ".omnigent"
    omni_dir.mkdir(parents=True, exist_ok=True)
    host_id = uuid.uuid4().hex
    host_name = f"e2e-cp1252-tunnel-{uuid.uuid4().hex[:12]}"
    (omni_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {"host": {"host_id": host_id, "name": host_name}},
            default_flow_style=False,
            sort_keys=True,
        )
    )

    # Build the daemon env through the real production builder, so a fix that
    # ships UTF-8 mode in the daemon env is exercised end to end.
    from omnigent.cli import _build_host_daemon_env

    env = _build_host_daemon_env(server_url=live_server)
    daemon_log = tmp_path / "host-daemon.log"
    env[PROCESS_LOG_FILE_ENV_VAR] = str(daemon_log)
    # Test-only isolation and worktree imports; not part of the env contract
    # under test. The ambient PYTHONPATH may carry entries relative to the
    # worktree (e.g. ``sdks/ui``); the daemon runs from tmp, so absolutize.
    env["OMNIGENT_DATA_DIR"] = str(tmp_path / "omnigent-data")
    ambient_pythonpath = os.environ.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_REPO_ROOT)]
        + [
            entry if os.path.isabs(entry) else str(_REPO_ROOT / entry)
            for entry in ambient_pythonpath.split(os.pathsep)
            if entry
        ]
    )
    apply_runner_env(env)

    stdio_log = tmp_path / "host-daemon-stdio.log"
    with open(stdio_log, "wb") as stdio_fh:
        proc = subprocess.Popen(
            [
                runner_executable(),
                "-c",
                _WINDOWS_ANSI_STDIO_BOOTSTRAP,
                live_server,
            ],
            env=env,
            cwd=str(tmp_path),
            stdin=subprocess.DEVNULL,
            stdout=stdio_fh,
            stderr=stdio_fh,
        )

    try:
        deadline = time.monotonic() + 90.0
        # Once online, the tunnel must then SURVIVE its own success print:
        # the crash lands within a second of registration, so a short grace
        # window separates "registered then died" from "registered and held".
        survival_deadline: float | None = None
        while time.monotonic() < deadline:
            crash = _crash_lines(_read_text(daemon_log), _read_text(stdio_log))
            if crash:
                pytest.fail(
                    "legacy-ANSI (cp1252) stdio killed the host tunnel: the "
                    "daemon's own status print raised UnicodeEncodeError and "
                    "tore down the connection (reconnect loop). Offending "
                    "log lines:\n" + "\n".join(crash[:8])
                )
            if proc.poll() is not None:
                pytest.fail(
                    f"host daemon exited rc={proc.returncode} before the "
                    "tunnel was established:\n"
                    + _read_text(daemon_log)[-2000:]
                    + _read_text(stdio_log)[-2000:]
                )
            if survival_deadline is None:
                if _host_online(http_client, host_id):
                    survival_deadline = time.monotonic() + 8.0
            elif time.monotonic() >= survival_deadline:
                assert _host_online(http_client, host_id), (
                    "host dropped offline after registering (tunnel did not "
                    "hold):\n" + _read_text(daemon_log)[-2000:]
                )
                return
            time.sleep(POLL_INTERVAL_S)
        pytest.fail(
            f"host {host_name!r} never came online within 90s — daemon log:\n"
            + _read_text(daemon_log)[-2000:]
            + _read_text(stdio_log)[-2000:]
        )
    finally:
        _terminate(proc)


def test_os_tools_start_under_windows_config_delivery_without_sandbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OS tools must work when config is delivered the Windows way, sandboxless.

    Journey: a session's runner builds its OS environment (no active sandbox —
    the only state Windows ever has), the agent runs one shell command through
    it, and the command's real output comes back. Today the helper client's
    Windows config-delivery branch asserts a scratch tmpdir that only an
    active sandbox creates, so the helper never starts and every OS tool call
    fails before doing any work.

    ``IS_WINDOWS`` is patched only in this (client) process — the helper
    subprocess imports the module fresh and serves the ops the real POSIX
    way, so the assertion exercises the client's spawn path, not a simulated
    helper.
    """
    monkeypatch.setattr(os_env_module, "IS_WINDOWS", True)

    spec = OSEnvSpec(
        type="caller_process",
        cwd=str(tmp_path),
        sandbox=OSEnvSandboxSpec(type="none"),
    )
    env = os_env_module.create_os_environment(spec)
    assert env is not None, "factory returned no OS environment"
    assert env.sandbox.active is False, (
        "precondition: the sandbox must be inactive (Windows never has an active one)"
    )

    marker = f"omni-degraded-os-tools-{uuid.uuid4().hex[:8]}"
    try:
        shell_result = asyncio.run(env.shell(f"echo {marker}"))
        read_result = asyncio.run(env.read("does-not-exist.txt"))
    finally:
        env.close()

    assert isinstance(shell_result, dict)
    assert not shell_result.get("error"), (
        f"sys_os_shell returned an error payload instead of running the command: {shell_result!r}"
    )
    assert shell_result.get("exit_code") == 0, f"unexpected result: {shell_result!r}"
    assert marker in (shell_result.get("stdout") or ""), (
        f"command output missing: {shell_result!r}"
    )
    # The read op must reach the helper too: a missing file is a normal
    # per-op error, not the helper-startup failure ("os_env helper failed"
    # / an AssertionError escaping before any op runs).
    assert isinstance(read_result, dict)
    assert "os_env helper failed" not in (read_result.get("error") or ""), (
        f"helper never started for the read op: {read_result!r}"
    )
