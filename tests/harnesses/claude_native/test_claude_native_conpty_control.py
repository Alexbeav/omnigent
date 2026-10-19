"""Real loopback bridge adoption with a portable renderer, no native process.

The lower transport tests own framing and authentication faults. These cases
exercise the runner publication and existing guarded Claude injection flow.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from omnigent.harnesses.claude_native import bridge
from omnigent.runner.native.orchestration import _publish_tmux_target_for_bridge
from omnigent.terminals import terminal_control as control
from omnigent.terminals.conpty import ConPTYSession
from omnigent.terminals.conpty_instance import ConPTYTerminalInstance
from omnigent.terminals.conpty_screen import ConPTYScreen
from tests.harnesses.claude_native.test_claude_native_bridge import _composer_pane
from tests.terminals.test_conpty import _Driver


class _ComposerDriver(_Driver):
    def render(self, text: str = "") -> None:
        pane = _composer_pane(text).replace("\n", "\r\n")
        self.output.put("\x1b[H\x1b[2J" + pane)

    def write(self, text: str) -> int:
        size = super().write(text)
        if text.startswith("\x1b[200~"):
            self.render(text[6:-6].strip().replace("\r", "\n"))
        elif text == "\r":
            self.render()
        return size


@pytest.fixture
def adopted(tmp_path, monkeypatch):
    directory, private = tmp_path / "bridge", tmp_path / "terminal"
    directory.mkdir(mode=0o700)
    private.mkdir(mode=0o700)
    driver = _ComposerDriver()
    session = ConPTYSession(driver, screen=ConPTYScreen(rows=24, cols=120))
    instance = ConPTYTerminalInstance(
        name="claude", session_key="main", socket_path=None, private_dir=private
    )
    instance._session, instance.running = session, True
    registry = SimpleNamespace(terminal_registry=SimpleNamespace(get=lambda *args: instance))
    monkeypatch.setattr(bridge, "bridge_dir_for_bridge_id", lambda _: directory)
    monkeypatch.setattr(bridge, "_PASTE_SETTLE_S", 0)
    monkeypatch.setattr(bridge, "_CLAUDE_READY_POLL_INTERVAL_S", 0.005)
    monkeypatch.setattr(bridge, "IS_WINDOWS", True)
    shell = Mock(side_effect=AssertionError("ConPTY must not shell out to tmux"))
    monkeypatch.setattr("subprocess.run", shell)
    _publish_tmux_target_for_bridge(
        resource_registry=registry,
        session_id="fixture",
        bridge_id="fixture",
        terminal_name="claude",
        session_key="main",
    )
    viewer = session.subscribe(replay=False)
    driver.render()
    assert viewer.read(timeout=1)
    try:
        yield directory, driver, session, instance
    finally:
        driver.allow_write.set()
        asyncio.run(instance.close())
    assert not session.workers_alive and not instance._control_server._thread.is_alive()
    shell.assert_not_called()


def test_runner_adopts_conpty_for_web_message_capture_interrupt_and_close(adopted) -> None:
    directory, driver, session, instance = adopted
    assert not (directory / "tmux.json").exists()
    info = bridge._wait_for_tmux_info(directory, timeout_s=0.1)
    assert isinstance(info["socket_path"], control.ConPTYControlTarget)
    assert bridge.claude_pane_ready(directory)
    assert bridge._claude_pane_state(info["socket_path"], info["tmux_target"]).alive
    bridge.inject_user_message(directory, content="Καλημέρα 😀\\\nsecond line", timeout_s=0.5)
    assert driver.operations == [
        "\x1b[97;5u",
        "\x1b[107;5u",
        "\x1b[200~Καλημέρα 😀\\\rsecond line\r\x1b[201~",
        "\r",
    ]
    bridge.inject_interrupt(directory, timeout_s=0.1)
    assert driver.operations[-1] == "\x1b"
    assert bridge.read_pane_signals(directory).permission_mode is None
    bridge.kill_session(directory, timeout_s=0.1)
    assert driver.closed and not session.alive
    assert not (directory / control.CONTROL_FILE).exists()
    assert instance.socket_path is None


def test_pending_approval_protects_conpty_before_any_input(adopted, monkeypatch) -> None:
    directory, driver, _, _ = adopted
    monkeypatch.setattr(bridge, "_has_approval_wait", lambda _: True)
    with pytest.raises(bridge.ClaudeUserPromptPending):
        bridge.inject_user_message(directory, content="must not answer approval", timeout_s=0.2)
    assert driver.operations == []


def test_uncertain_conpty_write_aborts_injection_without_paste_or_submit(
    adopted, monkeypatch
) -> None:
    directory, driver, session, _ = adopted
    monkeypatch.setattr(control, "_WRITE_SECONDS", 0.01)
    driver.allow_write.clear()
    with pytest.raises(control.DeliveryUncertain):
        bridge.inject_user_message(directory, content="never replay", timeout_s=0.2)
    with pytest.raises(control.DeliveryUncertain):
        bridge.inject_user_message(directory, content="never replay", timeout_s=0.2)
    driver.allow_write.set()
    session.write("barrier").result(timeout=1)
    assert driver.operations == ["\x1b[97;5u", "barrier"]


def test_windows_never_adopts_stale_tmux_or_plaintext_capability(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(bridge, "IS_WINDOWS", True)
    (tmp_path / "tmux.json").write_text('{"socket_path":"fake", "tmux_target":"fake"}')
    with pytest.raises(bridge.TmuxSessionNotAdvertised):
        bridge._wait_for_tmux_info(tmp_path, timeout_s=0.01)
    (tmp_path / control.CONTROL_FILE).write_text('{"backend":"conpty"}')
    (tmp_path / control.CONTROL_FILE).chmod(0o600)
    with pytest.raises(control.TerminalControlError):
        bridge._wait_for_tmux_info(tmp_path, timeout_s=0.1)
