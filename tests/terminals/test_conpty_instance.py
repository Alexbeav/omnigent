"""Managed Windows terminal behavior without a provider or native extension."""

from __future__ import annotations

import asyncio
import threading
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
