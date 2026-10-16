"""Built-SPA proof for async question controls in full chat and three panes."""

from __future__ import annotations

import re
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, Route, expect

from tests.browser_ui.chat.session_contract import (
    ChatSessionContract,
    _ChatSseStream,
    install_chat_session_routes,
    list_payload,
    message_item,
)


@pytest.mark.parametrize(
    ("pane_count", "source_index"),
    [(1, 0), (3, 0), (3, 1), (3, 2)],
    ids=["full-chat", "pane-1", "pane-2", "pane-3"],
)
def test_async_questions_survive_reload_and_reply_to_the_source_chat(
    page: Page,
    chat_session_contract: ChatSessionContract,
    tmp_path: Path,
    pane_count: int,
    source_index: int,
) -> None:
    # LAN HTTP has no SubtleCrypto. Exercise that boundary in the built SPA too.
    page.add_init_script("Object.defineProperty(window.crypto, 'subtle', { value: undefined })")
    chat = chat_session_contract
    with ExitStack() as cleanup:
        chats = [chat]
        for index in range(1, pane_count):
            stream = _ChatSseStream()
            cleanup.callback(stream.close)
            sibling = ChatSessionContract(
                page, chat.contract, stream, session_id=f"question-pane-{index}"
            )
            install_chat_session_routes(sibling)
            chats.append(sibling)
        rows = []
        sources = []
        for index, handle in enumerate(chats):
            handle.update_session(title=f"Question chat {index + 1}")
            source = message_item(
                f"source-{handle.session_id}",
                "assistant",
                f"Original native question text {index + 1}.",
                response_id=f"question-{index}",
            )
            source["model"] = handle.agent_id
            source["async_user_input"] = {
                "call_id": f"call-{index}",
                "reply_id": f"{index + 1:032x}",
                "questions": [
                    {
                        "title": f"Choose a route {index + 1}",
                        "options": ["First (Recommended)", "Second"],
                    },
                    {"title": "Describe your answer", "options": None},
                ],
            }
            sources.append(source)
            handle.set_items([] if pane_count == 1 else [source])
            rows.append(handle._session())
        chat.contract.json("/v1/sessions", list_payload(rows))
        page.set_viewport_size({"width": 1800, "height": 1100})
        page.goto(chat.url)
        chat.wait_for_stream()
        if pane_count == 1:
            chat.set_items([sources[0]])
            chat.emit({"event": "response.output_item.done", "data": {"item": sources[0]}})
        else:
            for count, sibling in enumerate(chats[1:], start=2):
                page.get_by_role("combobox", name="Add chat pane").select_option(
                    sibling.session_id
                )
                expect(page.locator("section[data-pane-id]")).to_have_count(count)
            expect(page.locator("section[data-pane-id]")).to_have_count(3)
        expect(page.get_by_test_id("async-question-card")).to_have_count(pane_count)
        assert all(not handle.event_posts for handle in chats)
        page.screenshot(path=str(tmp_path / "question-controls.png"))
        source_chat = chats[source_index]
        source = sources[source_index]
        root = (
            page
            if pane_count == 1
            else page.locator(f'section[data-pane-id="{source_chat.session_id}"]')
        )
        card = root.get_by_test_id("async-question-card")
        original = root.get_by_text(
            f"Original native question text {source_index + 1}.", exact=True
        )
        text_bounds = original.bounding_box()
        card_bounds = card.bounding_box()
        assert text_bounds is not None and card_bounds is not None
        assert 0 <= card_bounds["y"] - (text_bounds["y"] + text_bounds["height"]) < 40
        expect(card.get_by_label("First (Recommended)")).to_be_checked()
        card.get_by_label("Second").click()
        card.get_by_role("button", name="Next").click()
        card.get_by_placeholder("Type something").fill("My custom answer")
        composer = (
            root.get_by_label("Message the agent")
            if pane_count == 1
            else root.get_by_test_id("side-chat-input")
        )
        composer.fill("Preserve this composer draft")
        page.reload()
        root = (
            page
            if pane_count == 1
            else page.locator(f'section[data-pane-id="{source_chat.session_id}"]')
        )
        card = root.get_by_test_id("async-question-card")
        expect(card.get_by_placeholder("Type something")).to_have_value("My custom answer")
        expect(
            root.get_by_label("Message the agent")
            if pane_count == 1
            else root.get_by_test_id("side-chat-input")
        ).to_have_value("Preserve this composer draft")
        assert all(not handle.event_posts for handle in chats)
        held: list[Route] = []
        posted: list[dict[str, Any]] = []

        def hold_reply(route: Route) -> None:
            if route.request.method != "POST":
                route.fallback()
                return
            held.append(route)
            posted.append(route.request.post_data_json)

        chat.contract.route(
            re.compile(
                rf"^{re.escape(chat.contract.base_url)}/v1/sessions/{source_chat.session_id}/events$"
            ),
            hold_reply,
        )
        card.get_by_role("button", name="Submit").evaluate(
            "button => { button.click(); button.click(); }"
        )
        expect(card.get_by_role("status")).to_contain_text("Sending")
        if pane_count == 3:
            other_chat = chats[(source_index + 1) % pane_count]
            page.locator(f'section[data-pane-id="{other_chat.session_id}"]').get_by_test_id(
                "side-chat-input"
            ).fill("Other chat stays separate")
        expect(card.get_by_role("button", name="Retry delivery")).to_be_disabled()
        page.wait_for_function(
            "document.querySelectorAll('[data-testid=async-question-card] button').length > 0"
        )
        assert len(posted) == 1
        body = posted[0]["data"]
        assert body["async_question_reply"] == {
            "source_item_id": source["id"],
            "answers": {
                f"call-{source_index}:0": "Second",
                f"call-{source_index}:1": "My custom answer",
            },
            "cancelled": False,
        }
        assert len(body["stable_id"]) == 32
        held[0].fulfill(json={"queued": True, "pending_id": "pending-question"})
        expect(card.get_by_role("status")).to_contain_text("Reply queued")
        answer = message_item(
            body["stable_id"], "user", body["content"][0]["text"], response_id="answer-turn"
        )
        answer["async_question_reply"] = body["async_question_reply"]
        answer["user_authored"] = True
        source_chat.set_items([answer, source])
        page.reload()
        root = (
            page
            if pane_count == 1
            else page.locator(f'section[data-pane-id="{source_chat.session_id}"]')
        )
        card = root.get_by_test_id("async-question-card")
        expect(page.get_by_test_id("async-question-card")).to_have_count(pane_count)
        expect(card.get_by_role("status")).to_have_text("Answer submitted")
        expect(card.get_by_role("button", name="Submit")).to_have_count(0)
        expect(
            root.get_by_text(f"Original native question text {source_index + 1}.", exact=True)
        ).to_be_visible()
        expect(
            root.get_by_label("Message the agent")
            if pane_count == 1
            else root.get_by_test_id("side-chat-input")
        ).to_have_value("Preserve this composer draft")
        if pane_count == 3:
            expect(
                page.locator(f'section[data-pane-id="{other_chat.session_id}"]').get_by_test_id(
                    "side-chat-input"
                )
            ).to_have_value("Other chat stays separate")
        assert len(posted) == 1
        assert all(not handle.event_posts for handle in chats)
        page.screenshot(path=str(tmp_path / "question-answer-restored.png"))
