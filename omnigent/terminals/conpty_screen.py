"""Bounded VT screen capture for an explicitly enabled ConPTY terminal.

This is text/state capture, not a browser VT replay serializer. The session
owner serializes feed, resize and capture with the transport's output lock.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast
from unicodedata import combining

import pyte

_MAX_CELLS = 131_072
_MAX_CONTROL_CHARS = 4096
_ALTERNATE_MODES = frozenset({47, 1047, 1049})


class ScreenCaptureError(RuntimeError):
    """The capture cannot faithfully represent the terminal's current output."""


@dataclass(frozen=True)
class ScreenSnapshot:
    text: str
    rows: int
    cols: int
    cursor_row: int
    cursor_col: int
    alternate: bool
    bracketed_paste: bool
    cursor_visible: bool
    history_lines: int


class _Screens:
    """Keep normal history separate from an application's alternate screen."""

    def __init__(self, rows: int, cols: int, history: int) -> None:
        self.normal = pyte.HistoryScreen(cols, rows, history=history)
        self.alternate = pyte.Screen(cols, rows)
        self.active: pyte.Screen = self.normal
        self.private_modes = {7, 25}

    def __getattr__(self, event: str) -> Callable[..., None]:
        if event not in pyte.Stream.events:
            raise AttributeError(event)

        def dispatch(*args: object, **kwargs: object) -> None:
            getattr(self.active, event)(*args, **kwargs)

        return dispatch

    def reset(self) -> None:
        self.normal.reset()
        self.alternate.reset()
        self.active = self.normal
        self.private_modes = {7, 25}

    def draw(self, text: str) -> None:
        cursor = self.active.cursor
        x, y = max(0, cursor.x - 1), cursor.y
        if cursor.x == 0 and cursor.y:
            x, y = self.active.columns - 1, cursor.y - 1
        cluster = len(self.active.buffer[y][x].data)
        for char in text:
            cluster = cluster + 1 if combining(char) else 1
            if cluster > 32:
                raise ScreenCaptureError("Terminal glyph exceeds the capture bound.")
        self.active.draw(text)

    def set_mode(self, *modes: int, private: bool = False) -> None:
        self._mode(modes, private=private, enabled=True)

    def reset_mode(self, *modes: int, private: bool = False) -> None:
        self._mode(modes, private=private, enabled=False)

    def _mode(self, modes: tuple[int, ...], *, private: bool, enabled: bool) -> None:
        forwarded = []
        for mode in modes:
            if private:
                if enabled:
                    self.private_modes.add(mode)
                else:
                    self.private_modes.discard(mode)
                if mode in _ALTERNATE_MODES:
                    if enabled:
                        if self.active is self.normal and mode in {1047, 1049}:
                            self.alternate.reset()
                        self.active = self.alternate
                        if 25 not in self.private_modes:
                            self.alternate.reset_mode(25, private=True)
                    else:
                        self.active = self.normal
                    continue
                if mode == 3:
                    raise ScreenCaptureError("Terminal column-mode capture is unsupported.")
                if mode == 25:
                    for screen in (self.normal, self.alternate):
                        method = screen.set_mode if enabled else screen.reset_mode
                        method(mode, private=True)
                    continue
                if mode == 1048:
                    if enabled:
                        self.active.save_cursor()
                    else:
                        self.active.restore_cursor()
                    continue
            forwarded.append(mode)
        if forwarded:
            method = self.active.set_mode if enabled else self.active.reset_mode
            method(*forwarded, private=private)


class _BoundedStream(pyte.Stream):
    """Bound incomplete control strings before the parser retains more data."""

    def __init__(self, screens: _Screens) -> None:
        self._control_chars = 0
        # Stream binds only its declared event methods; dispatch stays dynamic.
        super().__init__(cast(pyte.Screen, screens))

    def _send_to_parser(self, data: str) -> bool | None:
        self._control_chars += len(data)
        if self._control_chars > _MAX_CONTROL_CHARS:
            raise ScreenCaptureError("Terminal control sequence exceeds the capture bound.")
        plain = super()._send_to_parser(data)
        if plain:
            self._control_chars = 0
        return plain


class ConPTYScreen:
    """Retain bounded normal history and alternate-screen text without a PTY."""

    def __init__(self, *, rows: int = 24, cols: int = 80, scrollback: int = 10000) -> None:
        self.validate_size(rows, cols)
        if type(scrollback) is not int or not 0 <= scrollback <= 10000:
            raise ValueError("Screen scrollback must be between 0 and 10000.")
        self._scrollback = scrollback
        self._screens = _Screens(rows, cols, self._history_limit(rows, cols))
        self._stream = _BoundedStream(self._screens)
        self._error = False

    @staticmethod
    def validate_size(rows: int, cols: int) -> None:
        if (
            type(rows) is not int
            or type(cols) is not int
            or not 1 <= rows <= 256
            or not 1 <= cols <= 512
            or 2 * rows * cols > _MAX_CELLS
        ):
            raise ValueError("Terminal dimensions exceed the bounded screen capture size.")

    def _history_limit(self, rows: int, cols: int) -> int:
        return min(self._scrollback, _MAX_CELLS // cols - 2 * rows)

    def feed(self, text: str) -> None:
        """Capture failures stay explicit without interrupting raw terminal I/O."""
        if self._error:
            return
        try:
            self._stream.feed(text)
        except Exception:  # Optional capture cannot interrupt raw I/O.
            self._error = True

    def resize(self, rows: int, cols: int) -> None:
        self.validate_size(rows, cols)
        history = self._screens.normal.history
        limit = self._history_limit(rows, cols)
        self._screens.normal.history = history._replace(
            top=deque(history.top, maxlen=limit),
            bottom=deque(history.bottom, maxlen=limit),
            size=limit,
            position=limit,
        )
        for screen in (self._screens.normal, self._screens.alternate):
            screen.resize(lines=rows, columns=cols)

    def capture(self, scrollback: int = 0) -> ScreenSnapshot:
        if self._error:
            raise ScreenCaptureError("Terminal screen capture is unavailable.")
        if type(scrollback) is not int or not 0 <= scrollback <= 10000:
            raise ValueError("Screen scrollback must be between 0 and 10000.")
        screen = self._screens.active
        lines = []
        if screen is self._screens.normal and scrollback:
            for line in list(self._screens.normal.history.top)[-scrollback:]:
                lines.append("".join(line[x].data for x in range(screen.columns)).rstrip())
        count = len(lines)
        lines.extend(line.rstrip() for line in screen.display)
        return ScreenSnapshot(
            text="\n".join(lines),
            rows=screen.lines,
            cols=screen.columns,
            cursor_row=screen.cursor.y,
            cursor_col=screen.cursor.x,
            alternate=screen is self._screens.alternate,
            bracketed_paste=2004 in self._screens.private_modes,
            cursor_visible=not screen.cursor.hidden,
            history_lines=count,
        )
