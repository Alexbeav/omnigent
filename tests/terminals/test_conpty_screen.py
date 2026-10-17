"""VT capture at the renderer boundary, with the existing owned driver stand-in."""

from __future__ import annotations

import contextlib

import pytest

from omnigent.terminals.conpty import ConPTYError, ConPTYSession
from omnigent.terminals.conpty_screen import ConPTYScreen, ScreenCaptureError
from tests.terminals.test_conpty import _Driver


@pytest.mark.parametrize("chunk", [1, 2, 7, 4096])
def test_fragmented_vt_capture_keeps_unicode_cursor_and_input_modes(chunk: int) -> None:
    screen = ConPTYScreen(rows=4, cols=40)
    text = "old text\rnew\x1b[K\r\nΕλληνικά 😀e\u0301\x1b[3;4H!\x1b[?25l\x1b[?2004h"
    for index in range(0, len(text), chunk):
        screen.feed(text[index : index + chunk])
    snapshot = screen.capture()
    assert snapshot.text.splitlines()[:3] == ["new", "Ελληνικά 😀é", "   !"]
    assert (snapshot.cursor_row, snapshot.cursor_col) == (2, 4)
    assert snapshot.bracketed_paste and not snapshot.cursor_visible
    assert not snapshot.alternate and not snapshot.history_lines


@pytest.mark.parametrize("mode", [47, 1047, 1049])
def test_alternate_screen_preserves_normal_contents_cursor_and_history(mode: int) -> None:
    screen = ConPTYScreen(rows=3, cols=20, scrollback=3)
    screen.feed("history\r\nnormal\r\nthird\r\nfourth\x1b[?25l")
    original = screen.capture(3)
    screen.feed(f"\x1b[?{mode}hALTERNATE\x1b[?2004h")
    alternate = screen.capture(3)
    assert alternate.alternate and alternate.text.splitlines()[0] == "ALTERNATE"
    assert not alternate.history_lines and not alternate.cursor_visible
    screen.feed(f"\x1b[?{mode}l")
    restored = screen.capture(3)
    assert restored.text == original.text
    assert (restored.cursor_row, restored.cursor_col) == (
        original.cursor_row,
        original.cursor_col,
    )
    assert restored.bracketed_paste and not restored.cursor_visible


@pytest.mark.parametrize("mode, retained", [(47, True), (1047, False), (1049, False)])
def test_alternate_reentry_has_explicit_clear_semantics(mode: int, retained: bool) -> None:
    screen = ConPTYScreen(rows=3, cols=20)
    screen.feed(f"\x1b[?{mode}hprior\x1b[?{mode}l\x1b[?{mode}h")
    assert ("prior" in screen.capture().text) is retained


def test_scrollback_is_bounded_and_screen_resize_preserves_current_buffer() -> None:
    screen = ConPTYScreen(rows=2, cols=8, scrollback=3)
    screen.feed("one\r\ntwo\r\nthree\r\nfour\r\nfive\r\nsix")
    assert screen.capture(100).text.splitlines() == ["two", "three", "four", "five", "six"]
    assert screen.capture(100).history_lines == 3
    screen.resize(4, 10)
    assert (screen.capture().rows, screen.capture().cols) == (4, 10)
    screen.feed("\x1b[?1049hALT")
    screen.resize(2, 12)
    assert screen.capture().alternate and screen.capture().cols == 12
    screen.feed("\x1b[?1049l")
    assert screen.capture().cols == 12 and not screen.capture().alternate


@pytest.mark.parametrize(
    "text",
    ["\x1b]0;" + "x" * 5000, "x" + "\u0301" * 100, "\x1b[?3h"],
)
def test_unsupported_or_unbounded_sequences_make_capture_unavailable(text: str) -> None:
    screen = ConPTYScreen()
    for index in range(0, len(text), 17):
        screen.feed(text[index : index + 17])
    with pytest.raises(ScreenCaptureError, match="capture is unavailable"):
        screen.capture()
    screen.feed("later raw output cannot silently repair an incomplete capture")
    with pytest.raises(ScreenCaptureError):
        screen.capture()


def test_combining_glyph_bound_survives_repeated_cursor_repositioning() -> None:
    screen = ConPTYScreen()
    screen.feed("a")
    for _ in range(100):
        screen.feed("\x1b[1;2H\u0301")
    with pytest.raises(ScreenCaptureError):
        screen.capture()


@pytest.mark.parametrize("rows, cols", [(0, 80), (257, 80), (256, 512), (24, True)])
def test_capture_size_rejection_does_not_enqueue_input_or_terminate_terminal(rows, cols) -> None:
    driver = _Driver()
    with contextlib.closing(ConPTYSession(driver, screen=ConPTYScreen())) as session:
        with pytest.raises(ValueError, match="dimensions"):
            session.resize(rows, cols)
        assert not driver.operations and driver.alive
    assert not session.workers_alive


def test_session_capture_is_atomic_with_published_output_and_survives_eof() -> None:
    driver = _Driver()
    with contextlib.closing(ConPTYSession(driver, screen=ConPTYScreen())) as session:
        viewer = session.subscribe()
        driver.output.put("first\rnew\x1b[K")
        assert viewer.read(timeout=1) == "first\rnew\x1b[K"
        assert session.capture().text.splitlines()[0] == "new"
        session.resize(30, 100).result(timeout=1)
        assert (session.capture().rows, session.capture().cols) == (30, 100)
        driver.output.put("\r\nfinal")
        driver.status, driver.alive = 7, False
        assert viewer.read(timeout=1) == "\r\nfinal"
        assert viewer.read(timeout=1) is None
        assert session.exit_status == 7 and "final" in session.capture().text
    assert not session.workers_alive


def test_capture_failure_preserves_raw_io_and_disabled_capture_is_explicit() -> None:
    driver = _Driver()
    with contextlib.closing(ConPTYSession(driver, screen=ConPTYScreen())) as session:
        viewer = session.subscribe()
        driver.output.put("\x1b[?3h")
        assert viewer.read(timeout=1) == "\x1b[?3h"
        with pytest.raises(ScreenCaptureError):
            session.capture()
        session.write("still live").result(timeout=1)
        assert driver.operations == ["still live"] and driver.alive
    driver = _Driver()
    with contextlib.closing(ConPTYSession(driver)) as session:
        with pytest.raises(ConPTYError, match="not enabled"):
            session.capture()
        assert driver.alive
    assert not session.workers_alive
