"""Real-browser coverage for transcript rendering that depends on layout or chunks."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path

import pytest
from playwright.sync_api import Locator, Page, Route, expect

from tests.browser_ui.chat.session_contract import (
    ChatSessionContract,
    _ChatSseStream,
    install_chat_session_routes,
    list_payload,
    message_item,
)

_CODE_BODY = '[data-streamdown="code-block-body"]'
_LONG_WORD = "horizontalScrolling" * 14
_SCROLL_CODE = "\n".join(f"const line{index} = '{_LONG_WORD}';" for index in range(60)) + "\n"
_TARGET = "https://example.com/docs/transcript"
_SEMICOLON_MERMAID = (
    "```mermaid\nsequenceDiagram\n"
    "    O->>O: Bind initiating user/run; check session policy\n"
    "    B->>B: Load grant#59; refresh if needed\n"
    "    G->>G: Record actor; target and outcome\n```"
)
_SEPARATOR_MERMAID = (
    "```mermaid\nsequenceDiagram\n"
    "    A->>B: first; B->>C: second\n"
    "    C->>D: punctuation; retry me\n```"
)
_INVALID_MERMAID = (
    "```mermaid\nsequenceDiagram\n"
    "    A->>B: hi\n"
    "    Note over A,B: proceed once; do not call Save\n"
    "    A=>B: again\n```"
)


@pytest.mark.parametrize("surface", ["main", "split", "mobile"])
def test_acp_working_notes_keep_the_final_reply_visible(
    page: Page, chat_session_contract: ChatSessionContract, tmp_path: Path, surface: str
) -> None:
    chat = chat_session_contract
    target = chat
    if surface == "split":
        target = ChatSessionContract(
            page, chat.contract, _ChatSseStream(), session_id="cline-notes-pane"
        )
        install_chat_session_routes(target)
    target.update_session(harness="acp:cline", title="Cline working notes")
    response_id = "notes-turn"
    items = [
        message_item("question", "user", "Check the sample setting.", response_id="user"),
        message_item(
            "notes", "assistant", "Checking the sample configuration.", response_id=response_id
        ),
        {
            "id": "check",
            "response_id": response_id,
            "type": "function_call",
            "status": "completed",
            "call_id": "check-call",
            "name": "read_file",
            "arguments": '{"path":"sample.json"}',
        },
        {
            "id": "result",
            "response_id": response_id,
            "type": "function_call_output",
            "status": "completed",
            "call_id": "check-call",
            "output": "enabled=true",
        },
        message_item(
            "answer", "assistant", "The sample setting is enabled.", response_id=response_id
        ),
    ]
    target.set_items(list(reversed(items)))
    if surface == "split":
        chat.contract.json("/v1/sessions", list_payload([chat._session(), target._session()]))
    page.set_viewport_size({"width": 390 if surface == "mobile" else 1600, "height": 900})
    page.goto(chat.url + (f"?panes={target.session_id}" if surface == "split" else ""))
    pane = (
        page.locator(f'section[data-pane-id="{target.session_id}"]')
        if surface == "split"
        else page
    )
    notes = pane.get_by_role("button", name="Working notes", exact=True)
    expect(notes).to_have_attribute("aria-expanded", "false")
    expect(pane.get_by_text("Checking the sample configuration.", exact=True)).not_to_be_visible()
    expect(pane.get_by_text("The sample setting is enabled.", exact=True)).to_be_visible()
    page.screenshot(path=str(tmp_path / f"working-notes-{surface}.png"), full_page=True)
    notes.click()
    expect(pane.get_by_text("Checking the sample configuration.", exact=True)).to_be_visible()
    expect(pane.get_by_text("The sample setting is enabled.", exact=True)).to_be_visible()
    persisted = page.evaluate(
        "async url => (await (await fetch(url)).json()).data",
        f"/v1/sessions/{target.session_id}/items",
    )
    assert persisted == list(reversed(items))
    page.reload()
    expect(notes).to_have_attribute("aria-expanded", "false")
    expect(pane.get_by_text("The sample setting is enabled.", exact=True)).to_be_visible()
    assert not chat.contract.violations, chat.contract.violations


def _seed_assistant_message(chat: ChatSessionContract, text: str) -> None:
    chat.set_items(
        [
            message_item(
                "transcript-rendering-assistant",
                "assistant",
                text,
                response_id="transcript-rendering-response",
            )
        ]
    )


def _position_code_block(block: Locator) -> None:
    block.evaluate(
        """block => {
            const scroller = document.querySelector('[role="log"]').firstElementChild;
            scroller.scrollTop += block.getBoundingClientRect().top
                - scroller.getBoundingClientRect().top - 96;
        }"""
    )


def _assert_code_controls_follow_header(page: Page, block: Locator) -> None:
    _position_code_block(block)
    page.locator('[role="log"] > div').first.evaluate("el => { el.scrollTop += 200; }")
    page.wait_for_function(
        """() => {
            const block = document.querySelector('[data-streamdown="code-block"]').parentElement;
            const scroller = document.querySelector('[role="log"]').firstElementChild;
            const header = block.querySelector('[data-streamdown="code-block-header"]');
            const buttons = ['Toggle word wrap', 'Copy Code', 'Download file'].map(name =>
                [...block.querySelectorAll('button')].find(button =>
                    button.getAttribute('aria-label') === name || button.title === name
                )?.getBoundingClientRect()
            );
            if (buttons.some(rect => !rect)) return false;
            const headerRect = header.getBoundingClientRect();
            const headerCenter = headerRect.top + headerRect.height / 2;
            return headerRect.bottom < scroller.getBoundingClientRect().top
                && buttons.every(rect => Math.abs(rect.top + rect.height / 2 - headerCenter) < 2);
        }"""
    )


@pytest.mark.parametrize("width", [1280, 390], ids=["desktop", "mobile"])
def test_code_block_wrap_toggle_controls_horizontal_overflow(
    page: Page,
    chat_session_contract: ChatSessionContract,
    width: int,
) -> None:
    """Long code fits by default and overflows only when wrapping is disabled."""
    chat = chat_session_contract
    _seed_assistant_message(chat, f"```ts\n{_SCROLL_CODE}```")
    page.set_viewport_size({"width": width, "height": 844})
    page.goto(chat.url)

    body = page.locator(_CODE_BODY).first
    block = page.locator('[data-streamdown="code-block"]').first.locator("..")
    toggle = page.get_by_role("button", name="Toggle word wrap")
    expect(body).to_be_visible(timeout=20_000)
    expect(toggle).to_have_attribute("aria-pressed", "true")
    page.wait_for_function(
        "selector => { const el = document.querySelector(selector); "
        "return !!el && el.scrollWidth - el.clientWidth <= 1; }",
        arg=_CODE_BODY,
    )

    _assert_code_controls_follow_header(page, block)

    toggle.click()
    expect(toggle).to_have_attribute("aria-pressed", "false")
    page.wait_for_function(
        "selector => { const el = document.querySelector(selector); "
        "return !!el && el.scrollWidth - el.clientWidth > 1; }",
        arg=_CODE_BODY,
    )
    body.evaluate("el => { el.scrollLeft = 200; }")
    _assert_code_controls_follow_header(page, block)

    toggle.click()
    expect(toggle).to_have_attribute("aria-pressed", "true")
    page.wait_for_function(
        "selector => { const el = document.querySelector(selector); "
        "return !!el && el.scrollWidth - el.clientWidth <= 1; }",
        arg=_CODE_BODY,
    )

    _position_code_block(block)
    scroller = page.locator('[role="log"] > div').first
    scroll_top = scroller.evaluate("el => el.scrollTop")
    with page.expect_download() as download_info:
        block.get_by_role("button", name="Download file").click()
    download = download_info.value
    assert download.suggested_filename.endswith(".ts")
    assert Path(download.path()).read_text() == _SCROLL_CODE
    assert abs(scroller.evaluate("el => el.scrollTop") - scroll_top) < 2
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_code_block_highlights_against_the_built_bundle(
    page: Page,
    chat_session_contract: ChatSessionContract,
) -> None:
    """The production Shiki chunks replace the raw fallback with colored tokens."""
    chat = chat_session_contract
    _seed_assistant_message(chat, "```ts\nconst answer = 42;\n```")
    page.goto(chat.url)

    tokens = page.locator(f'{_CODE_BODY} span[style*="--sdm-c"]')
    page.wait_for_function(
        """selector => {
            const spans = [...document.querySelectorAll(selector)];
            return spans.length > 1
                && new Set(spans.map(span => getComputedStyle(span).color)).size > 1;
        }""",
        arg=f'{_CODE_BODY} span[style*="--sdm-c"]',
        timeout=20_000,
    )
    expect(tokens.filter(has_text="const").first).to_be_visible()
    expect(tokens.filter(has_text="42").first).to_be_visible()


def test_mermaid_fence_loads_its_chunk_and_renders_svg(
    page: Page,
    chat_session_contract: ChatSessionContract,
) -> None:
    """The built SPA serves Mermaid's lazy chunk and renders a real diagram."""
    chat = chat_session_contract
    _seed_assistant_message(
        chat,
        "```mermaid\nflowchart LR\n  A[Client] --> B[Server]\n```",
    )
    page.goto(chat.url)

    block = page.locator('[data-streamdown="mermaid-block"]').first
    expect(block).to_be_visible(timeout=20_000)
    expect(block.locator("svg[aria-roledescription]")).to_be_visible(timeout=20_000)


@pytest.mark.parametrize("diagram", ["semicolons", "separators", "invalid"])
def test_mermaid_recovery_uses_the_real_browser_renderer(
    page: Page,
    chat_session_contract: ChatSessionContract,
    diagram: str,
) -> None:
    """Mermaid accepts escaped prose, preserves separators, and explains errors."""
    chat = chat_session_contract
    markdown = {
        "semicolons": _SEMICOLON_MERMAID,
        "separators": _SEPARATOR_MERMAID,
        "invalid": _INVALID_MERMAID,
    }[diagram]
    _seed_assistant_message(chat, markdown)
    page.goto(chat.url)

    if diagram == "invalid":
        card = page.get_by_test_id("mermaid-error")
        expect(card).to_be_visible(timeout=20_000)
        expect(card).to_contain_text("Mermaid couldn't parse line 3")
        expect(card.locator("pre > code")).to_have_text(
            "Note over A,B: proceed once; do not call Save"
        )
        expect(card.locator("details")).to_contain_text("got 'NEWLINE'")
        return

    escaped = page.get_by_test_id("mermaid-escaped")
    diagram_svg = escaped.locator("svg[aria-roledescription]")
    expect(diagram_svg).to_be_visible(timeout=20_000)
    if diagram == "semicolons":
        expect(diagram_svg.locator("text.messageText")).to_have_text(
            [
                "Bind initiating user/run; check session policy",
                "Load grant; refresh if needed",
                "Record actor; target and outcome",
            ]
        )
        expect(escaped).to_contain_text("2 semicolons escaped as #59; (first on line 2)")
        expect(escaped.locator("details")).to_contain_text("Load grant#59; refresh if needed")
    else:
        expect(diagram_svg.locator("text.messageText")).to_have_text(
            ["first", "second", "punctuation; retry me"]
        )
        expect(escaped).to_contain_text("one semicolon escaped as #59; (first on line 3)")
    expect(page.get_by_test_id("mermaid-error")).to_have_count(0)


@pytest.mark.parametrize("activation", ["click", "keyboard", "context-menu"])
def test_external_link_click_opens_the_rendered_target(
    page: Page,
    chat_session_contract: ChatSessionContract,
    activation: str,
) -> None:
    """A transcript link keeps its browser-level new-tab navigation contract."""
    chat = chat_session_contract
    _seed_assistant_message(chat, f"Read the [rendering guide]({_TARGET}).")
    requests: list[dict[str, str]] = []

    def fulfill_target(route: Route) -> None:
        requests.append(route.request.all_headers())
        route.fulfill(content_type="text/html", body="<title>Rendering guide</title>")

    page.context.route(
        _TARGET,
        fulfill_target,
    )
    page.goto(chat.url)

    link = page.get_by_role("link", name="rendering guide")
    expect(link).to_have_attribute("href", _TARGET)
    with page.expect_popup() as popup_info:
        if activation == "click":
            link.click()
        elif activation == "keyboard":
            link.press("Enter")
        else:
            link.click(button="right")
            page.get_by_role("menuitem", name="Open in browser tab").click()
    popup = popup_info.value
    popup.wait_for_url(_TARGET)
    expect(page).to_have_url(chat.url)
    assert popup.url == _TARGET
    assert popup.evaluate("window.opener === null")
    assert popup.evaluate("document.referrer") == ""
    assert requests and "referer" not in requests[0]
    assert len(page.context.pages) == 2


@pytest.mark.parametrize("pane_count", [1, 3], ids=["full-chat", "three-panes"])
def test_file_link_context_menu_targets_its_source_chat(
    page: Page, chat_session_contract: ChatSessionContract, tmp_path: Path, pane_count: int
) -> None:
    chat = chat_session_contract
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.set_viewport_size({"width": 1800, "height": 1100})
    with ExitStack() as cleanup:
        chats = [chat]
        for index in range(1, pane_count):
            stream = _ChatSseStream()
            cleanup.callback(stream.close)
            sibling = ChatSessionContract(
                page, chat.contract, stream, session_id=f"link-pane-{index}"
            )
            install_chat_session_routes(sibling)
            chats.append(sibling)
        source = chats[pane_count // 2]
        _seed_assistant_message(source, "Open [my report](report.md:12).")
        environment = f"/v1/sessions/{source.session_id}/resources/environments/default"
        chat.contract.json(environment, {"metadata": {"root": "/browser-workspace"}})
        chat.contract.json(f"{environment}/changes", list_payload([]))
        chat.contract.json(f"/v1/sessions/{source.session_id}/comments", list_payload([]))
        chat.contract.json(
            f"{environment}/filesystem",
            list_payload([{"path": "report.md", "name": "report.md", "type": "file"}]),
        )
        chat.contract.json(
            f"{environment}/filesystem/report.md",
            {
                "object": "session.environment.filesystem.file_content",
                "path": "report.md",
                "content": "# My report\n\nThis is the source chat's report.",
                "encoding": "utf-8",
                "content_type": "text/markdown",
                "bytes": 46,
            },
        )
        chat.contract.json("/v1/sessions", list_payload([handle._session() for handle in chats]))
        suffix = "" if pane_count == 1 else "?panes=" + ",".join(c.session_id for c in chats[1:])
        page.goto(chat.url + suffix)
        root = (
            page
            if pane_count == 1
            else page.locator(f'section[data-pane-id="{source.session_id}"]')
        )
        link = root.get_by_role("button", name="my report", exact=True)
        link.click(button="right")
        expect(page.get_by_role("menuitem", name="Open in Omnigent")).to_be_enabled()
        expect(page.get_by_role("menuitem", name="Open in browser tab")).to_be_enabled()
        page.screenshot(path=str(tmp_path / f"file-link-menu-{pane_count}.png"))
        page.get_by_role("menuitem", name="Copy link", exact=True).click()
        expected = f"{chat.base_url}/c/{source.session_id}?file=report.md&line=12"
        assert page.evaluate("navigator.clipboard.readText()") == expected
        link.click(button="right")
        with page.expect_popup() as opened:
            page.get_by_role("menuitem", name="Open in browser tab").click()
        opened.value.wait_for_url(expected)
        assert opened.value.evaluate("window.opener === null")
        opened.value.close()
        link.click(button="right")
        page.get_by_role("menuitem", name="Open in Omnigent", exact=True).click()
        expect(page.locator('[data-testid="file-viewer"]:visible').first).to_be_visible()
        assert page.url.startswith(f"{chat.base_url}/c/{source.session_id}?")
        assert all(not handle.event_posts for handle in chats)


@pytest.mark.parametrize("activation", ["click", "keyboard"])
def test_external_link_falls_back_inside_a_popup_blocked_host(
    page: Page,
    chat_session_contract: ChatSessionContract,
    activation: str,
) -> None:
    """A sandboxed embed follows links in-frame without leaking its referrer."""
    chat = chat_session_contract
    _seed_assistant_message(chat, f"Read the [rendering guide]({_TARGET}).")
    requests: list[dict[str, str]] = []

    def fulfill_target(route: Route) -> None:
        requests.append(route.request.all_headers())
        route.fulfill(
            content_type="text/html",
            body="<title>Rendering guide</title><p>target-ok</p>",
        )

    page.context.route(_TARGET, fulfill_target)
    host_url = f"{chat.base_url}/popup-blocked-host"
    host_html = (
        '<!doctype html><html><body style="margin:0"><iframe id="embed" '
        'sandbox="allow-scripts allow-same-origin allow-forms" '
        f'src="{chat.url}" style="width:100vw;height:100vh;border:0"></iframe></body></html>'
    )
    page.route(
        host_url,
        lambda route: route.fulfill(status=200, content_type="text/html", body=host_html),
    )
    page.goto(host_url)

    frame = page.frame_locator("#embed")
    link = frame.get_by_role("link", name="rendering guide")
    expect(link).to_be_visible(timeout=20_000)
    if activation == "click":
        link.click()
    else:
        link.focus()
        link.press("Enter")

    body = frame.locator("body")
    expect(body).to_contain_text("target-ok", timeout=10_000)
    assert body.evaluate("el => el.ownerDocument.referrer") == ""
    assert requests and "referer" not in requests[0]
    expect(page).to_have_url(host_url)
    assert len(page.context.pages) == 1
    assert any(frame.url == _TARGET for frame in page.frames)
