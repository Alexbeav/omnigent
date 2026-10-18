"""Bounded VT screen capture for an explicitly enabled ConPTY terminal.

This is text/state capture, not a browser VT replay serializer. The session
owner serializes feed, resize and capture with the transport's output lock.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast
from unicodedata import combining, normalize
from weakref import ReferenceType, ref

import pyte
from pyte.modes import DECAWM
from pyte.screens import Char, StaticDefaultDict
from wcwidth import wcwidth

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


class _Row(StaticDefaultDict[int, Char]):
    """Wrap provenance moves with cells; weak links cannot retain evicted rows."""

    def __init__(self, default: Char, columns: int) -> None:
        super().__init__(default)
        self.columns = columns
        self.generation = 0
        self.wrap_next: ReferenceType[_Row] | None = None
        self.wrap_generation = 0
        self.wrap_end = 0
        self.clipped = False

    def erase(self) -> None:
        self.generation += 1
        self.wrap_next = None
        self.wrap_end = 0
        self.clipped = False

    def continues(self, following: _Row) -> bool:
        return (
            self.wrap_next is not None
            and self.wrap_next() is following
            and self.wrap_generation == following.generation
        )

    def text(self, end: int) -> str:
        cells, x = [], 0
        while x < end:
            data = self[x].data or " "
            cells.append(data)
            x += max(1, wcwidth(data[0]))
        return "".join(cells)


class _Screens:
    """Keep normal history separate from an application's alternate screen."""

    def __init__(self, rows: int, cols: int, history: int) -> None:
        self.normal = pyte.HistoryScreen(cols, rows, history=history)
        # Reverse-scroll pagination is not exposed by the VT stream or capture API.
        self.normal.history = self.normal.history._replace(bottom=deque(maxlen=0))
        self.alternate = pyte.Screen(cols, rows)
        for screen in (self.normal, self.alternate):
            screen.buffer = defaultdict(
                lambda screen=screen: _Row(screen.default_char, screen.columns)
            )
        self.active: pyte.Screen = self.normal
        self.private_modes = {7, 25}

    def __getattr__(self, event: str) -> Callable[..., None]:
        if event not in pyte.Stream.events:
            raise AttributeError(event)

        def dispatch(*args: object, **kwargs: object) -> None:
            self._before_event(event, args)
            getattr(self.active, event)(*args, **kwargs)

        return dispatch

    def _before_event(self, event: str, args: tuple[object, ...]) -> None:
        screen = self.active
        row = cast(_Row, screen.buffer[screen.cursor.y])
        if event.startswith("cursor_") or event in {
            "linefeed",
            "index",
            "reverse_index",
            "backspace",
            "tab",
        }:
            screen.cursor.x = min(screen.cursor.x, screen.columns - 1)
        if event in {"linefeed", "index"}:
            row.wrap_next = None
            row.wrap_end = 0
        elif event == "erase_in_line":
            how = args[0] if args else 0
            if (
                how == 2
                or (how == 0 and screen.cursor.x == 0)
                or (how == 1 and screen.cursor.x >= screen.columns - 1)
            ):
                row.erase()
        elif event in {"erase_in_display", "alignment_display"}:
            how = args[0] if args else 0
            for y in range(screen.lines):
                if (
                    event == "alignment_display"
                    or how in {2, 3}
                    or (y > screen.cursor.y if how == 0 else y < screen.cursor.y)
                ):
                    cast(_Row, screen.buffer[y]).erase()
            if event == "erase_in_display" and how in {0, 1}:
                self._before_event("erase_in_line", (how,))

    def reset(self) -> None:
        self.normal.reset()
        self.alternate.reset()
        self.active = self.normal
        self.private_modes = {7, 25}

    def draw(self, text: str) -> None:
        screen = self.active
        for char in text:
            translated = char.translate(screen.g1_charset if screen.charset else screen.g0_charset)
            width = wcwidth(translated)
            if combining(translated):
                self._combine(translated)
                continue
            if width <= 0 or width > screen.columns:
                raise ScreenCaptureError("Terminal glyph cannot be captured faithfully.")
            if screen.cursor.x + width > screen.columns and DECAWM in screen.mode:
                previous = cast(_Row, screen.buffer[screen.cursor.y])
                end = screen.cursor.x
                if end < screen.columns:
                    self._clear_wide_cells(end, 1)
                    previous[end] = screen.cursor.attrs._replace(data=" ")
                screen.carriage_return()
                screen.linefeed()
                following = cast(_Row, screen.buffer[screen.cursor.y])
                if following is not previous:
                    previous.wrap_next = ref(following)
                    previous.wrap_generation = following.generation
                    previous.wrap_end = end
            elif width == 2 and screen.cursor.x + width > screen.columns:
                raise ScreenCaptureError("Wide glyph at a disabled wrap boundary is unsupported.")
            row = cast(_Row, screen.buffer[screen.cursor.y])
            if row.wrap_next is not None:
                row.wrap_end = max(row.wrap_end, min(screen.cursor.x + width, screen.columns))
            self._clear_wide_cells(min(screen.cursor.x, screen.columns - width), width)
            screen.draw(char)

    def _clear_wide_cells(self, start: int, width: int) -> None:
        screen = self.active
        row = screen.buffer[screen.cursor.y]
        for x in range(start, start + width):
            data = row[x].data
            if not data and x:
                row[x - 1] = screen.cursor.attrs._replace(data=" ")
            elif data and wcwidth(data[0]) == 2:
                row[x + 1] = screen.cursor.attrs._replace(data=" ")

    def _combine(self, char: str) -> None:
        screen = self.active
        x, y = screen.cursor.x - 1, screen.cursor.y
        if x < 0:
            if not y:
                return
            x, y = screen.columns - 1, y - 1
        row = screen.buffer[y]
        if not row[x].data and x:
            x -= 1  # A wide glyph's second cell belongs to its first cell.
        data = normalize("NFC", row[x].data + char)
        if len(data) > 32:
            raise ScreenCaptureError("Terminal glyph exceeds the capture bound.")
        row[x] = row[x]._replace(data=data)
        screen.dirty.add(y)

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

    def _history_limit(self, rows: int, cols: int, history_cols: int = 0) -> int:
        return min(self._scrollback, (_MAX_CELLS - 2 * rows * cols) // max(cols, history_cols))

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
        limit = self._history_limit(
            rows, cols, max((cast(_Row, row).columns for row in history.top), default=cols)
        )
        self._screens.normal.history = history._replace(
            top=deque(history.top, maxlen=limit),
            bottom=deque(maxlen=0),
            size=limit,
            position=limit,
        )
        for screen in (self._screens.normal, self._screens.alternate):
            if cols < screen.columns:
                for row in screen.buffer.values():
                    tracked = cast(_Row, row)
                    tracked.clipped |= tracked.wrap_end > cols or any(
                        (x >= cols and char.data.strip())
                        or (x == cols - 1 and char.data and wcwidth(char.data[0]) == 2)
                        for x, char in row.items()
                    )
            screen.resize(lines=rows, columns=cols)
            for row in screen.buffer.values():
                cast(_Row, row).columns = cols

    def capture(self, scrollback: int = 0, *, join_wrapped: bool = False) -> ScreenSnapshot:
        if self._error:
            raise ScreenCaptureError("Terminal screen capture is unavailable.")
        if type(scrollback) is not int or not 0 <= scrollback <= 10000:
            raise ValueError("Screen scrollback must be between 0 and 10000.")
        screen = self._screens.active
        lines = []
        history = []
        if screen is self._screens.normal and scrollback:
            history = list(self._screens.normal.history.top)[-scrollback:]
            for line in history:
                lines.append("".join(line[x].data for x in range(screen.columns)).rstrip())
        count = len(lines)
        if join_wrapped:
            retained = [cast(_Row, row) for row in history]
            retained.extend(cast(_Row, screen.buffer[y]) for y in range(screen.lines))
            lines = self._joined_lines(retained)
        else:
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

    @staticmethod
    def _joined_lines(rows: list[_Row]) -> list[str]:
        lines, pending = [], []
        for index, row in enumerate(rows):
            if row.clipped:
                raise ScreenCaptureError(
                    "Joined capture is unavailable after terminal text was clipped."
                )
            continues = index + 1 < len(rows) and row.continues(rows[index + 1])
            end = row.wrap_end if continues else row.columns
            pending.append(row.text(end))
            if not continues:
                lines.append("".join(pending).rstrip())
                pending.clear()
        return lines
