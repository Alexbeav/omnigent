"""Experimental, session-owned ConPTY transport; not a native harness launcher.

The reader drains independently of serialized input. Browser consumers get
bounded subscriptions; detaching one never terminates the child. Importing this
module does not import the Windows extension or change platform readiness.
"""

from __future__ import annotations

import importlib
import os
import queue
import shutil
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import Future
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from omnigent._platform import IS_WINDOWS
from omnigent.runner.identity import RUNNER_AUTH_SECRET_ENV_VARS
from omnigent.terminals.attach_target import ConPTYAttachTarget

if TYPE_CHECKING:
    from omnigent.terminals.conpty_screen import ConPTYScreen, ScreenSnapshot

_OUTPUT_CHUNK_CHARS = 16_384
_REPLAY_CHARS = 131_072
_INPUT_BYTES = 4 * 1024 * 1024
_POLL_SECONDS = 0.01


class ConPTYError(RuntimeError):
    """A transport failure, without input, output or environment contents."""


class OutputOverflow(ConPTYError):
    """A slow viewer must reconnect instead of rendering an incomplete stream."""


class PTYDriver(Protocol):
    """Blocking OS operations; reads must be nonblocking."""

    @property
    def pid(self) -> int: ...

    def read(self) -> str: ...
    def write(self, text: str) -> int | None:
        """Return completed bytes, or None for accepted buffered input."""
        ...

    def resize(self, rows: int, cols: int) -> None: ...
    def is_alive(self) -> bool: ...
    def exit_status(self) -> int | None: ...
    def terminate(self) -> None: ...
    def close(self) -> None: ...


class OutputSubscription:
    """One bounded viewer queue. ``None`` is EOF, not a skipped output chunk."""

    def __init__(self, capacity: int) -> None:
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=capacity)
        self._error: ConPTYError | None = None
        self._ended = False

    def read(self, timeout: float | None = None) -> str | None:
        """Read output; raises ``queue.Empty`` on timeout or an explicit error."""
        if self._error is not None:
            raise self._error
        if self._ended:
            return None
        item = self._queue.get(timeout=timeout)
        if self._error is not None:
            raise self._error
        self._ended = item is None
        return item

    def _finish(self, error: ConPTYError | None = None) -> None:
        self._error = error
        if error is not None:
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            self._finish(OutputOverflow("Terminal viewer fell behind; reconnect."))


@dataclass
class _Operation:
    text: str | None
    size: tuple[int, int] | None
    future: Future[None]
    byte_count: int = 0


class ConPTYSession:
    """Own a driver, two I/O workers and bounded output until explicit close.

    The Windows factory is separate so lifecycle and backpressure faults can be
    exercised on every platform. Accepted writes remain atomic when a caller
    stops waiting for its future. No shell commands or automatic submit retries
    are synthesized here.
    """

    def __init__(self, driver: PTYDriver, *, screen: ConPTYScreen | None = None) -> None:
        self._driver = driver
        self._screen = screen
        self._lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._closing = threading.Event()
        self._reader_stop = threading.Event()
        self._ended = threading.Event()
        self._closed = False
        self._replay = ""
        self._subscribers: set[OutputSubscription] = set()
        self._viewer_sizes: dict[OutputSubscription, tuple[int, int]] = {}
        self._effective_size: tuple[int, int] | None = None
        self._operations: queue.Queue[_Operation] = queue.Queue(maxsize=64)
        self._input_bytes = 0
        self._exit_status: int | None = None
        self._output_error: ConPTYError | None = None
        self._reader = threading.Thread(target=self._read_loop, name="conpty-reader", daemon=True)
        self._writer = threading.Thread(target=self._write_loop, name="conpty-writer", daemon=True)
        self._reader.start()
        self._writer.start()

    @property
    def pid(self) -> int:
        return self._driver.pid

    @property
    def attach_target(self) -> ConPTYAttachTarget:
        return ConPTYAttachTarget(self)

    @property
    def exit_status(self) -> int | None:
        return self._exit_status

    @property
    def alive(self) -> bool:
        """Reader-owned liveness, without racing the native binding's output reads."""
        return not self._ended.is_set() and not self._closing.is_set()

    @property
    def workers_alive(self) -> bool:
        return self._reader.is_alive() or self._writer.is_alive()

    def subscribe(self, *, replay: bool = True, capacity: int = 64) -> OutputSubscription:
        """Attach atomically with replay; this is a raw VT tail, not a screen."""
        if capacity < 2 or capacity > 256:
            raise ValueError("Terminal subscription capacity must be between 2 and 256.")
        viewer = OutputSubscription(capacity)
        with self._lock:
            if replay and self._replay:
                viewer._queue.put_nowait(self._replay)
            if self._ended.is_set():
                viewer._finish(self._output_error)
            else:
                self._subscribers.add(viewer)
        return viewer

    def unsubscribe(self, viewer: OutputSubscription) -> None:
        """Release only this viewer; the session and other viewers keep running."""
        with self._lock:
            self._subscribers.discard(viewer)
            self._viewer_sizes.pop(viewer, None)
            viewer._finish()
            with suppress(ConPTYError):
                self._resize_viewers_locked()

    def set_viewer_size(
        self, viewer: OutputSubscription, rows: int, cols: int
    ) -> Future[None] | None:
        """Writable viewers constrain the shared terminal to the smallest size."""
        if not (1 <= rows <= 32767 and 1 <= cols <= 32767):
            raise ValueError("Terminal dimensions must be between 1 and 32767.")
        if self._screen is not None:
            self._screen.validate_size(rows, cols)
        with self._lock:
            if viewer not in self._subscribers:
                return None
            self._viewer_sizes[viewer] = (rows, cols)
            return self._resize_viewers_locked()

    def _resize_viewers_locked(self) -> Future[None] | None:
        if not self._viewer_sizes or self._closing.is_set() or self._ended.is_set():
            return None
        size = (
            min(rows for rows, _ in self._viewer_sizes.values()),
            min(cols for _, cols in self._viewer_sizes.values()),
        )
        if size == self._effective_size:
            return None
        future = self._enqueue_locked(_Operation(None, size, Future()))
        self._effective_size = size
        return future

    def write(self, text: str) -> Future[None]:
        """Enqueue one payload; completion means accepted, not child consumption."""
        size = len(text.encode("utf-8"))
        return self._enqueue(_Operation(text, None, Future(), size))

    def resize(self, rows: int, cols: int) -> Future[None]:
        if not (1 <= rows <= 32767 and 1 <= cols <= 32767):
            raise ValueError("Terminal dimensions must be between 1 and 32767.")
        if self._screen is not None:
            self._screen.validate_size(rows, cols)
        return self._enqueue(_Operation(None, (rows, cols), Future()))

    def capture(self, scrollback: int = 0, *, join_wrapped: bool = False) -> ScreenSnapshot:
        """Capture rendered text under the same lock as output publication."""
        if self._screen is None:
            raise ConPTYError("Terminal screen capture is not enabled.")
        with self._lock:
            return self._screen.capture(scrollback, join_wrapped=join_wrapped)

    def _enqueue(self, operation: _Operation) -> Future[None]:
        with self._lock:
            return self._enqueue_locked(operation)

    def _enqueue_locked(self, operation: _Operation) -> Future[None]:
        if self._closing.is_set() or self._ended.is_set():
            raise ConPTYError("Terminal is closed.")
        if self._input_bytes + operation.byte_count > _INPUT_BYTES:
            raise ConPTYError("Terminal input queue is full.")
        try:
            self._operations.put_nowait(operation)
        except queue.Full:
            raise ConPTYError("Terminal input queue is full.") from None
        self._input_bytes += operation.byte_count
        return operation.future

    def _publish(self, text: str) -> None:
        with self._lock:
            if self._screen is not None:
                self._screen.feed(text)
            self._replay = (self._replay + text)[-_REPLAY_CHARS:]
            for viewer in tuple(self._subscribers):
                try:
                    viewer._queue.put_nowait(text)
                except queue.Full:
                    viewer._finish(OutputOverflow("Terminal viewer fell behind; reconnect."))
                    self._subscribers.remove(viewer)
                    self._viewer_sizes.pop(viewer, None)

    def _read_loop(self) -> None:
        try:
            while not self._reader_stop.is_set():
                text = self._driver.read()
                if text:
                    for offset in range(0, len(text), _OUTPUT_CHUNK_CHARS):
                        self._publish(text[offset : offset + _OUTPUT_CHUNK_CHARS])
                    continue
                if not self._driver.is_alive():
                    self._exit_status = self._driver.exit_status()
                    break
                self._reader_stop.wait(_POLL_SECONDS)
        except Exception:
            with suppress(Exception):
                self._exit_status = self._driver.exit_status()
            if self._exit_status is None and not self._closing.is_set():
                self._output_error = ConPTYError("Terminal output read failed.")
        finally:
            with self._lock:
                self._ended.set()
                for viewer in self._subscribers:
                    viewer._finish(self._output_error)
                self._subscribers.clear()
                self._viewer_sizes.clear()

    def _write_loop(self) -> None:
        while True:
            try:
                operation = self._operations.get(timeout=_POLL_SECONDS)
            except queue.Empty:
                if self._closing.is_set() or self._ended.is_set():
                    return
                continue
            try:
                # Once accepted, cancellation of a waiting caller cannot split a paste.
                if not operation.future.set_running_or_notify_cancel():
                    continue
                if self._closing.is_set() or self._ended.is_set():
                    raise ConPTYError("Terminal is closed.")
                if operation.text is not None:
                    written = self._driver.write(operation.text)
                    if written is not None and written != operation.byte_count:
                        raise ConPTYError("Terminal input write was incomplete.")
                elif operation.size is not None:
                    self._driver.resize(*operation.size)
                    if self._screen is not None:
                        with self._lock:
                            self._screen.resize(*operation.size)
                operation.future.set_result(None)
            except Exception:
                # Never retry a possibly partial write or expose the payload in errors.
                operation.future.set_exception(ConPTYError("Terminal input operation failed."))
                terminate = not self._closing.is_set()
                self._closing.set()
                if terminate:
                    with suppress(Exception):
                        self._driver.terminate()
            finally:
                with self._lock:
                    self._input_bytes -= operation.byte_count

    def close(self, *, timeout: float = 2.0) -> None:
        """Terminate owned processes, drain output and join both I/O workers."""
        with self._close_lock:
            if self._closed:
                return
            deadline = time.monotonic() + timeout
            self._closing.set()
            terminate_failed = False
            try:
                self._driver.terminate()
            except Exception:
                terminate_failed = True
            self._reader.join(min(0.5, max(0, deadline - time.monotonic())))
            self._reader_stop.set()
            self._reader.join(max(0, deadline - time.monotonic()) / 2)
            self._writer.join(max(0, deadline - time.monotonic()))
            if self.workers_alive:
                raise ConPTYError("Terminal I/O workers did not stop before the deadline.")
            if terminate_failed:
                raise ConPTYError("Terminal process cleanup could not be confirmed; retry close.")
            self._driver.close()
            self._closed = True


class _NativePTY(Protocol):
    pid: int | None

    def spawn(self, appname: str, *, cmdline: str, cwd: str, env: str) -> bool: ...
    def read(self, *, blocking: bool) -> str: ...
    def write(self, text: str) -> int: ...
    def set_size(self, cols: int, rows: int) -> None: ...
    def isalive(self) -> bool: ...
    def get_exitstatus(self) -> int | None: ...
    def cancel_io(self) -> bool: ...


class _WinPTYModule(Protocol):
    def PTY(self, cols: int, rows: int, *, backend: int) -> _NativePTY: ...


class _ProcessIdentity(Protocol):
    @property
    def pid(self) -> int: ...

    def is_running(self) -> bool: ...
    def kill(self) -> None: ...
    def terminate(self) -> None: ...


@dataclass(eq=False)
class _OwnedChild:
    process: _ProcessIdentity

    @property
    def pid(self) -> int:
        return self.process.pid

    @property
    def returncode(self) -> int | None:
        return None if self.process.is_running() else 0

    def terminate(self) -> None:
        self.process.terminate()

    def kill(self) -> None:
        self.process.kill()


class _WindowsDriver:
    def __init__(self, pty: _NativePTY) -> None:
        import psutil

        from omnigent.inner import _proc
        from omnigent.inner.sandbox import SandboxPolicy
        from omnigent.inner.windows_jobobject_sandbox import WindowsJobObjectSandboxBackend

        if pty.pid is None:
            raise ConPTYError("ConPTY did not return a child process identity.")
        self._pty: _NativePTY | None = pty
        self._terminate_lock = threading.Lock()
        self.pid = pty.pid
        self._process = psutil.Process(self.pid)
        self.birth_time: float = self._process.create_time()
        self._child = _OwnedChild(self._process)
        _proc.refresh_process_tree(self._child)
        job = WindowsJobObjectSandboxBackend().post_spawn(
            SandboxPolicy("windows_jobobject", True, None, [], [], True), self.pid
        )
        if job is None:
            # A failed containment setup must not enable an unmanaged native CLI.
            _proc.kill_tree(self._child)
            raise ConPTYError("ConPTY child could not be assigned to an owned Job Object.")
        self._job = job

    def _native(self) -> _NativePTY:
        if self._pty is None:
            raise ConPTYError("Terminal is closed.")
        return self._pty

    def read(self) -> str:
        return self._native().read(blocking=False)

    def write(self, text: str) -> None:
        # ConPTY's overlapped counter can describe a previous write, even zero.
        # A successful call accepts this input; completion is not exposed.
        self._native().write(text)

    def resize(self, rows: int, cols: int) -> None:
        self._native().set_size(cols, rows)

    def is_alive(self) -> bool:
        return self._native().isalive()

    def exit_status(self) -> int | None:
        return self._native().get_exitstatus()

    def terminate(self) -> None:
        with self._terminate_lock:
            self._job.close()
            with suppress(Exception):
                self._native().cancel_io()

    def close(self) -> None:
        self._pty = None


def spawn_conpty(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    rows: int = 24,
    cols: int = 80,
    capture_screen: bool = False,
    scrollback: int = 10000,
) -> ConPTYSession:
    """Start an explicit Windows pilot; production readiness remains gated.

    Environment is caller-owned and copied. Never interpret argv as shell text;
    batch launchers need an explicit adapter before they can use this transport.
    """
    if not IS_WINDOWS:
        raise ConPTYError("ConPTY requires native Windows.")
    if not argv or not argv[0] or any("\0" in arg for arg in argv):
        raise ValueError("Terminal argv must contain an executable and no NUL characters.")
    if not (1 <= rows <= 32767 and 1 <= cols <= 32767):
        raise ValueError("Terminal dimensions must be between 1 and 32767.")
    screen = None
    if capture_screen:
        try:
            from omnigent.terminals.conpty_screen import ConPTYScreen
        except ImportError:
            raise ConPTYError("Install the windows-native extra for terminal capture.") from None
        screen = ConPTYScreen(rows=rows, cols=cols, scrollback=scrollback)
    clean_env = {
        key: value for key, value in env.items() if key.upper() not in RUNNER_AUTH_SECRET_ENV_VARS
    }
    if any(not key or "=" in key or "\0" in key + value for key, value in clean_env.items()):
        raise ValueError("Invalid terminal environment entry.")
    command = shutil.which(argv[0], path=clean_env.get("PATH", os.defpath))
    if command is None:
        raise ConPTYError("Terminal executable was not found.")
    if Path(command).suffix.lower() in {".cmd", ".bat"}:
        raise ConPTYError("Batch launchers require an explicit native executable adapter.")
    if not cwd.is_dir():
        raise ConPTYError("Terminal working directory does not exist.")
    try:
        winpty = cast(_WinPTYModule, importlib.import_module("winpty"))
    except ImportError:
        raise ConPTYError("Install the experimental windows-native extra for ConPTY.") from None
    # Backend.ConPTY == 0: do not silently fall back to the legacy console host.
    environment = (
        "\0".join(
            f"{key}={value}"
            for key, value in sorted(clean_env.items(), key=lambda item: item[0].upper())
        )
        + "\0\0"
    )
    try:
        pty = winpty.PTY(cols, rows, backend=0)
        if not pty.spawn(
            command,
            cmdline=" " + subprocess.list2cmdline(list(argv[1:])),
            cwd=str(cwd),
            env=environment,
        ):
            raise ConPTYError("ConPTY child process did not start.")
        driver = _WindowsDriver(pty)
    except ConPTYError:
        raise
    except Exception:
        raise ConPTYError("ConPTY startup failed.") from None
    return ConPTYSession(driver, screen=screen)
