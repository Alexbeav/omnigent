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


@pytest.mark.parametrize("chunk", [1, 3, 4096])
@pytest.mark.parametrize("ending", ["\r\n", "\n\r", "\r\x1bD"])
def test_joining_uses_observed_wraps_and_preserves_full_width_hard_lines(
    chunk: int, ending: str
) -> None:
    screen = ConPTYScreen(rows=6, cols=4)
    text = "abcd" + ending + "EFGH\r\n12  34\x1b[31m56"
    for index in range(0, len(text), chunk):
        screen.feed(text[index : index + chunk])
    assert screen.capture().text == "abcd\nEFGH\n12\n3456\n\n"
    assert screen.capture(join_wrapped=True).text == "abcd\nEFGH\n12  3456\n\n"


@pytest.mark.parametrize("chunk", [1, 2, 4096])
def test_joined_unicode_wraps_use_cells_and_keep_combining_marks_on_the_base(chunk: int) -> None:
    screen = ConPTYScreen(rows=4, cols=4)
    text = "ab界\u0301\x1b[32me\u0301😀z\r\nabc界!"
    for index in range(0, len(text), chunk):
        screen.feed(text[index : index + chunk])
    assert screen.capture().text == "ab界́\né😀z\nabc\n界!"
    assert screen.capture(join_wrapped=True).text == "ab界́é😀z\nabc界!"


def test_wraps_follow_bounded_history_and_the_history_screen_boundary() -> None:
    screen = ConPTYScreen(rows=2, cols=4, scrollback=2)
    screen.feed("00001111222233334444")
    assert screen.capture(100).text == "1111\n2222\n3333\n4444"
    snapshot = screen.capture(100, join_wrapped=True)
    assert snapshot.text == "1111222233334444" and snapshot.history_lines == 2
    assert screen.capture(1, join_wrapped=True).text == "222233334444"
    assert screen.capture(join_wrapped=True).text == "33334444"
    screen.feed("\r\nHARD")
    assert screen.capture(100, join_wrapped=True).text == "222233334444\nHARD"


def test_history_wraps_keep_their_original_width_when_only_the_grid_shrinks() -> None:
    screen = ConPTYScreen(rows=2, cols=6, scrollback=3)
    screen.feed("abcdefghi\r\nLAST")
    screen.resize(2, 4)
    assert screen.capture(3, join_wrapped=True).text == "abcdefghi\nLAST"
    assert screen.capture(3).text == "abcd\nghi\nLAST"


def test_wraps_follow_scroll_regions_without_joining_surrounding_rows() -> None:
    screen = ConPTYScreen(rows=4, cols=4)
    screen.feed("TOP\x1b[4;1HBOT\x1b[2;3r\x1b[2;1Habcdefghijkl")
    assert screen.capture(join_wrapped=True).text == "TOP\nefghijkl\nBOT"
    screen.feed("\x1b[2;1H\x1bMNEW")
    assert screen.capture(join_wrapped=True).text == "TOP\nNEW\nefgh\nBOT"


@pytest.mark.parametrize("mode", [47, 1047, 1049])
def test_joined_wraps_are_isolated_between_alternate_and_normal_screens(mode: int) -> None:
    screen = ConPTYScreen(rows=3, cols=4)
    screen.feed("normal\x1b[?" + str(mode) + "hother")
    assert screen.capture(100, join_wrapped=True).text == "other\n"
    screen.feed(f"\x1b[?{mode}l")
    assert screen.capture(100, join_wrapped=True).text == "normal\n"


@pytest.mark.parametrize("edit", ["\x1b[1;1H\x1b[2K", "\x1b[2;1H\x1b[2K", "\x1b[2J"])
def test_erasing_a_wrapped_row_breaks_its_connections(edit: str) -> None:
    screen = ConPTYScreen(rows=3, cols=4)
    screen.feed("abcdef" + edit)
    assert screen.capture(join_wrapped=True).text == screen.capture().text


@pytest.mark.parametrize("erase", ["\x1b[K", "\x1b[J"])
def test_erasing_only_the_tail_preserves_the_existing_wrap(erase: str) -> None:
    screen = ConPTYScreen(rows=3, cols=4)
    screen.feed("abcdef" + erase)
    assert screen.capture(join_wrapped=True).text == "abcdef\n"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("界\x1b[1;2HX", " X"),
        ("界\rX", "X"),
        ("zzzz\rabc界", "abc界"),
        ("界z\r\x1b[4hA", "A界z"),
    ],
)
def test_wide_overwrites_and_wrap_padding_cannot_retain_stale_cells(
    text: str, expected: str
) -> None:
    screen = ConPTYScreen(rows=2, cols=4)
    screen.feed(text)
    assert screen.capture(join_wrapped=True).text.rstrip("\n") == expected


@pytest.mark.parametrize(
    "edit, expected",
    [("\x1b[2;1H\x1b[L", "abcd\n\nefghijkl"), ("\x1b[2;1H\x1b[M", "abcd\nijkl\n\n")],
)
def test_row_insert_delete_cannot_join_new_neighbors(edit: str, expected: str) -> None:
    screen = ConPTYScreen(rows=4, cols=4)
    screen.feed("abcdefghijkl" + edit)
    assert screen.capture(join_wrapped=True).text == expected


def test_autowrap_disabled_overwrites_without_creating_a_join() -> None:
    screen = ConPTYScreen(rows=3, cols=4)
    screen.feed("\x1b[?7labcdef\r\nNEXT")
    assert screen.capture(join_wrapped=True).text == "abcf\nNEXT\n"


def test_lf_at_the_right_margin_keeps_the_column_without_a_phantom_wrap() -> None:
    screen = ConPTYScreen(rows=3, cols=4)
    screen.feed("abcd\nX")
    assert screen.capture(join_wrapped=True).text == "abcd\n   X\n"


def test_cr_overwrite_preserves_a_wrap_that_already_happened() -> None:
    screen = ConPTYScreen(rows=3, cols=4)
    screen.feed("abcdef\x1b[1;1H\rX")
    assert screen.capture(join_wrapped=True).text == "Xbcdef\n"


def test_joined_resize_preserves_surviving_row_links_and_original_wrap_width() -> None:
    screen = ConPTYScreen(rows=3, cols=4)
    screen.feed("abcdefghij")
    screen.resize(2, 6)
    assert screen.capture(join_wrapped=True).text == "efghij"
    screen.feed("\x1b[?1049h12345678")
    screen.resize(4, 8)
    assert screen.capture(join_wrapped=True).text == "12345678\n\n"
    screen.feed("\x1b[?1049l")
    assert screen.capture(join_wrapped=True).text == "efghij\n\n"


def test_destructive_resize_refuses_joined_capture_until_clipped_rows_are_erased() -> None:
    screen = ConPTYScreen(rows=2, cols=4)
    screen.feed("abcdef")
    screen.resize(2, 3)
    assert screen.capture().text == "abc\nef"
    with pytest.raises(ScreenCaptureError, match="clipped"):
        screen.capture(join_wrapped=True)
    screen.feed("\x1b[2J\x1b[H12345")
    assert screen.capture(join_wrapped=True).text == "12345"


@pytest.mark.parametrize("text, cols", [("😀\u200d😀", 8), ("❤\ufe0f", 8), ("界", 1)])
def test_unrepresentable_glyphs_refuse_capture_instead_of_dropping_text(
    text: str, cols: int
) -> None:
    screen = ConPTYScreen(rows=2, cols=cols)
    screen.feed(text)
    with pytest.raises(ScreenCaptureError):
        screen.capture(join_wrapped=True)


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
