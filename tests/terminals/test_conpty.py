"""Portable ConPTY lifecycle faults; real Windows coverage is a separate lane.

No server fixture owns this low-level driver boundary. The stand-in controls
pipe pressure and EOF explicitly; it does not launch a shell or use sign-ins.
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest

from omnigent.terminals import conpty


class _Driver:
    pid = 123

    def __init__(self) -> None:
        self.output: queue.Queue[str | Exception] = queue.Queue()
        self.operations: list[str | tuple[int, int]] = []
        self.alive = True
        self.status: int | None = None
        self.writing = threading.Event()
        self.allow_write = threading.Event()
        self.allow_write.set()
        self.closed = False
        self.short_write = False

    def read(self) -> str:
        try:
            item = self.output.get_nowait()
        except queue.Empty:
            return ""
        if isinstance(item, Exception):
            raise item
        return item

    def write(self, text: str) -> int:
        self.writing.set()
        if not self.allow_write.wait(timeout=2):
            raise RuntimeError("test writer was not released")
        self.operations.append(text)
        return 0 if self.short_write else len(text.encode("utf-8"))

    def resize(self, rows: int, cols: int) -> None:
        self.operations.append((rows, cols))

    def is_alive(self) -> bool:
        return self.alive

    def exit_status(self) -> int | None:
        return self.status

    def terminate(self) -> None:
        self.status = 137 if self.status is None else self.status
        self.alive = False
        self.allow_write.set()

    def close(self) -> None:
        self.closed = True


def test_independent_reader_atomic_input_resize_and_detach() -> None:
    driver = _Driver()
    driver.allow_write.clear()
    session = conpty.ConPTYSession(driver)
    viewer = session.subscribe()
    other = session.subscribe()
    try:
        paste = "\x1b[200~Καλημέρα\nsecond line\x1b[201~\r"
        first = session.write(paste)
        assert driver.writing.wait(timeout=1)
        assert first.cancel() is False  # An in-flight paste cannot be split.
        second = session.write("x")
        size = session.resize(36, 120)
        driver.output.put("still draining while input is blocked")
        assert viewer.read(timeout=1) == "still draining while input is blocked"
        session.unsubscribe(viewer)
        assert other.read(timeout=1) == "still draining while input is blocked"
        assert driver.alive
        driver.allow_write.set()
        for future in (first, second, size):
            future.result(timeout=1)
        assert driver.operations == [paste, "x", (36, 120)]
        driver.output.put("after detach")
        assert other.read(timeout=1) == "after detach"
    finally:
        session.close()
    assert driver.closed
    assert not session.workers_alive
    assert viewer.read(timeout=1) is None


def test_slow_viewer_disconnects_explicitly_without_blocking_other_viewers() -> None:
    driver = _Driver()
    session = conpty.ConPTYSession(driver)
    slow = session.subscribe(capacity=2)
    fast = session.subscribe()
    try:
        for chunk in ("\x1b[31m", "red", "\x1b[0m"):
            driver.output.put(chunk)
            assert fast.read(timeout=1) == chunk
        with pytest.raises(conpty.OutputOverflow, match="reconnect"):
            slow.read(timeout=1)
        session.write("still works").result(timeout=1)
        reconnect = session.subscribe()
        assert reconnect.read(timeout=1) == "\x1b[31mred\x1b[0m"
    finally:
        session.close()
    assert not session.workers_alive


def test_replay_is_bounded_and_exit_keeps_final_output() -> None:
    driver = _Driver()
    session = conpty.ConPTYSession(driver)
    viewer = session.subscribe()
    try:
        driver.output.put("λ" * (conpty._REPLAY_CHARS + 1))
        received = ""
        while len(received) < conpty._REPLAY_CHARS + 1:
            received += viewer.read(timeout=1) or ""
        driver.output.put("\r\nfinal diagnostic")
        driver.status = 7
        driver.alive = False
        assert viewer.read(timeout=1) == "\r\nfinal diagnostic"
        assert viewer.read(timeout=1) is None
        assert session.exit_status == 7
        late = session.subscribe()
        replay = late.read(timeout=1)
        assert replay is not None and len(replay) == conpty._REPLAY_CHARS
        assert replay.endswith("final diagnostic")
        assert late.read(timeout=1) is None
    finally:
        session.close()
    assert not session.workers_alive


def test_close_unblocks_writer_drains_pending_operations_and_is_idempotent() -> None:
    driver = _Driver()
    driver.allow_write.clear()
    session = conpty.ConPTYSession(driver)
    first = session.write("pending")
    assert driver.writing.wait(timeout=1)
    pending = session.write("must not be sent after close")
    viewer = session.subscribe()
    session.close()
    first.result(timeout=1)
    with pytest.raises(conpty.ConPTYError):
        pending.result(timeout=1)
    session.close()
    assert driver.operations == ["pending"]
    assert driver.closed
    assert not session.workers_alive
    assert viewer.read(timeout=1) is None
    with pytest.raises(conpty.ConPTYError, match="closed"):
        session.write("late")


def test_short_write_is_never_retried_and_stops_later_input() -> None:
    driver = _Driver()
    driver.allow_write.clear()
    driver.short_write = True
    session = conpty.ConPTYSession(driver)
    try:
        first = session.write("private test input")
        assert driver.writing.wait(timeout=1)
        pending = session.write("must not run")
        driver.allow_write.set()
        for future in (first, pending):
            with pytest.raises(conpty.ConPTYError) as error:
                future.result(timeout=1)
            assert "private" not in str(error.value)
        assert driver.operations == ["private test input"]
    finally:
        session.close()
    assert not session.workers_alive


def test_read_error_has_no_private_output_and_wakes_viewers() -> None:
    driver = _Driver()
    session = conpty.ConPTYSession(driver)
    viewer = session.subscribe()
    try:
        driver.output.put(RuntimeError("private output and environment"))
        with pytest.raises(conpty.ConPTYError, match=r"^Terminal output read failed\.$"):
            viewer.read(timeout=1)
        late = session.subscribe()
        with pytest.raises(conpty.ConPTYError, match=r"^Terminal output read failed\.$"):
            late.read(timeout=1)
        with pytest.raises(conpty.ConPTYError, match="closed"):
            session.write("late")
    finally:
        session.close()
    assert not session.workers_alive


def test_input_queue_is_byte_bounded_and_cancelled_pending_write_is_skipped() -> None:
    driver = _Driver()
    driver.allow_write.clear()
    session = conpty.ConPTYSession(driver)
    try:
        first = session.write("a")
        assert driver.writing.wait(timeout=1)
        cancelled = session.write("cancelled before it started")
        assert cancelled.cancel()
        with pytest.raises(conpty.ConPTYError, match="queue is full"):
            session.write("λ" * (conpty._INPUT_BYTES // 2))
        driver.allow_write.set()
        first.result(timeout=1)
        session.write("last").result(timeout=1)
        assert driver.operations == ["a", "last"]
    finally:
        session.close()
    assert not session.workers_alive


def test_cleanup_failure_retains_ownership_and_can_be_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = _Driver()
    session = conpty.ConPTYSession(driver)
    terminate = driver.terminate
    monkeypatch.setattr(driver, "terminate", Mock(side_effect=RuntimeError("private error")))
    try:
        with pytest.raises(conpty.ConPTYError, match="cleanup could not be confirmed"):
            session.close()
        assert not session.workers_alive
        assert driver.alive and not driver.closed
    finally:
        monkeypatch.setattr(driver, "terminate", terminate)
        session.close()
    assert driver.closed and not driver.alive


def test_factory_rejects_non_windows_before_loading_optional_extension(tmp_path: Path) -> None:
    if conpty.IS_WINDOWS:
        pytest.skip("The non-Windows import boundary is exercised on POSIX.")
    with pytest.raises(conpty.ConPTYError, match="requires native Windows"):
        conpty.spawn_conpty(["not-a-real-command"], cwd=tmp_path, env={})


def test_factory_passes_literal_argv_unicode_cwd_and_scrubbed_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(conpty, "IS_WINDOWS", True)
    monkeypatch.setattr(conpty.shutil, "which", lambda *a, **k: "C:/Python/python.exe")
    native = Mock()
    native.spawn.return_value = True
    extension = Mock()
    extension.PTY.return_value = native
    monkeypatch.setattr(conpty.importlib, "import_module", lambda name: extension)
    driver = _Driver()
    monkeypatch.setattr(conpty, "_WindowsDriver", lambda pty: driver)
    cwd = tmp_path / "Ελληνικά with spaces"
    cwd.mkdir()
    environment = {
        "SystemRoot": "C:/Windows",
        "PATH": "C:/Python",
        "omnigent_runner_tunnel_binding_token": "private-lower-case",
        "OMNIGENT_RUNNER_INITIAL_AUTH_TOKEN": "private-upper-case",
    }
    session = conpty.spawn_conpty(
        ["python", "fixture.py", "literal & $() | argument"], cwd=cwd, env=environment
    )
    try:
        extension.PTY.assert_called_once_with(80, 24, backend=0)
        args, kwargs = native.spawn.call_args
        assert args == ("C:/Python/python.exe",)
        assert kwargs["cmdline"] == ' fixture.py "literal & $() | argument"'
        assert kwargs["cwd"] == str(cwd)
        assert kwargs["env"] == "PATH=C:/Python\0SystemRoot=C:/Windows\0\0"
        assert "OMNIGENT_RUNNER_INITIAL_AUTH_TOKEN" in environment  # Caller state is unchanged.
    finally:
        session.close()
    assert not session.workers_alive


@pytest.mark.parametrize("argv", [[], [""], ["python", "bad\0argument"]])
def test_factory_rejects_invalid_argv_before_spawn(
    argv: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(conpty, "IS_WINDOWS", True)
    with pytest.raises(ValueError, match="argv"):
        conpty.spawn_conpty(argv, cwd=tmp_path, env={})


def test_containment_failure_cleans_owned_process_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psutil

    from omnigent.inner import _proc
    from omnigent.inner.windows_jobobject_sandbox import WindowsJobObjectSandboxBackend

    root = Mock(pid=12345)
    root.is_running.return_value = True
    root.create_time.return_value = 100.5
    monkeypatch.setattr(psutil, "Process", lambda pid: root)
    census = Mock()
    cleanup = Mock()
    monkeypatch.setattr(_proc, "refresh_process_tree", census)
    monkeypatch.setattr(_proc, "kill_tree", cleanup)
    monkeypatch.setattr(WindowsJobObjectSandboxBackend, "post_spawn", lambda *args: None)
    native = Mock(pid=12345)
    with pytest.raises(conpty.ConPTYError, match="owned Job Object"):
        conpty._WindowsDriver(native)
    child = census.call_args.args[0]
    assert child.pid == 12345
    assert child.returncode is None
    cleanup.assert_called_once_with(child)
    child.kill()
    root.kill.assert_called_once()


def test_factory_hides_private_startup_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(conpty, "IS_WINDOWS", True)
    monkeypatch.setattr(conpty.shutil, "which", lambda *a, **k: "C:/Python/python.exe")
    extension = Mock()
    extension.PTY.side_effect = RuntimeError("private startup environment")
    monkeypatch.setattr(conpty.importlib, "import_module", lambda name: extension)
    with pytest.raises(conpty.ConPTYError, match=r"^ConPTY startup failed\.$"):
        conpty.spawn_conpty(["python"], cwd=tmp_path, env={})


def test_windows_buffered_write_counts_do_not_replay_or_reject_accepted_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psutil

    from omnigent.inner import _proc
    from omnigent.inner.windows_jobobject_sandbox import WindowsJobObjectSandboxBackend

    process = Mock()
    process.create_time.return_value = 100.5
    monkeypatch.setattr(psutil, "Process", lambda pid: process)
    monkeypatch.setattr(_proc, "refresh_process_tree", Mock())
    native = Mock(pid=12345)
    native.read.return_value = ""
    native.isalive.return_value = True
    native.get_exitstatus.side_effect = lambda: None if native.isalive() else 137
    # The native counter can be zero or describe a previous overlapped write.
    native.write.side_effect = [0, 1000, RuntimeError("private native error")]
    job = Mock()
    job.close.side_effect = lambda: setattr(native.isalive, "return_value", False)
    monkeypatch.setattr(WindowsJobObjectSandboxBackend, "post_spawn", lambda *args: job)
    session = conpty.ConPTYSession(conpty._WindowsDriver(native))
    try:
        session.write("Καλημέρα 😀\r").result(timeout=1)
        session.write("second\r").result(timeout=1)
        with pytest.raises(conpty.ConPTYError, match=r"^Terminal input operation failed\.$"):
            session.write("third\r").result(timeout=1)
        assert [call.args[0] for call in native.write.call_args_list] == [
            "Καλημέρα 😀\r",
            "second\r",
            "third\r",
        ]
    finally:
        session.close()
    assert not session.workers_alive
    job.close.assert_called()


@pytest.mark.windows_only
@pytest.mark.parametrize("capture_screen", [False, True])
def test_windows_conpty_two_turns_reconnect_resize_and_owned_child_cleanup(
    tmp_path: Path, capture_screen: bool
) -> None:
    from tests.terminals.conpty_probe import run_probe

    result = run_probe(tmp_path, capture_screen=capture_screen)
    assert result["status"] == "passed"
    assert result["owned_processes_remaining"] == 0
    assert result["io_workers_remaining"] == 0
