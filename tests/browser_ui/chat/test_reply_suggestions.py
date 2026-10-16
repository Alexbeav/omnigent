"""Suggested drafts across the actual full-chat and uniform-pane composers."""

from __future__ import annotations

import re
from contextlib import suppress

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, Route, expect

from tests.browser_ui.chat.session_contract import (
    ChatSessionContract,
    _ChatSseStream,
    install_chat_session_routes,
    list_payload,
    message_item,
    model_option,
)


def enable(page: Page) -> None:
    page.add_init_script("localStorage.setItem('omnigent:reply-suggestions:local', 'on')")


def finish(chat: ChatSessionContract, response_id: str) -> None:
    chat.emit_busy(response_id)
    # Let the UI observe the live turn before its matching terminal event.
    chat.page.wait_for_timeout(100)
    assistant = message_item(
        f"assistant-{response_id}",
        "assistant",
        f"Finished {response_id}.",
        response_id=response_id,
    )
    chat.emit({"event": "response.output_item.done", "data": {"item": assistant}})
    chat.emit_idle(response_id)


@pytest.mark.parametrize("harness", ["codex-native", "claude-native"])
def test_full_chat_prediction_is_an_editable_unsent_draft(
    page: Page, chat_session_contract, tmp_path, harness
) -> None:
    chat = chat_session_contract
    chat.set_catalog(
        harness=harness, models=[model_option("main-model")], selected_model="main-model"
    )
    enable(page)
    requests = []

    def suggestion(route: Route) -> None:
        requests.append(route.request.post_data_json)
        route.fulfill(json={"status": "ready", "text": "Show the diff."})

    chat.contract.route(re.compile(rf"/v1/sessions/{chat.session_id}/next-reply$"), suggestion)
    page.goto(chat.url)
    chat.wait_for_stream()
    composer = page.get_by_role("textbox", name="Message the agent", exact=True)
    expect(composer).to_be_visible()
    composer.click()
    finish(chat, "first")
    expect(composer).to_have_attribute("placeholder", "Show the diff.")
    expect(composer).to_have_value("")
    page.screenshot(path=str(tmp_path / f"{harness}-ghost.png"), full_page=True)
    composer.press("Tab")
    expect(composer).to_have_value("Show the diff.")
    composer.fill("Show only the browser changes.")
    assert chat.event_posts == []
    assert len(requests) == 1
    page.screenshot(path=str(tmp_path / f"{harness}-editable-draft.png"), full_page=True)
    assert not chat.contract.violations, chat.contract.violations


def test_three_panes_keep_predictions_and_dismissal_on_their_own_session(
    page: Page, chat_session_contract, tmp_path
) -> None:
    primary = chat_session_contract
    primary.set_catalog(
        harness="codex-native", models=[model_option("main-model")], selected_model="main-model"
    )
    chats = [primary]
    streams = []
    for index, harness in enumerate(("claude-native", "codex-native")):
        stream = _ChatSseStream()
        streams.append(stream)
        child = ChatSessionContract(
            page,
            primary.contract,
            stream,
            session_id=f"reply-pane-{index}",
            harness=harness,
            models=[model_option("main-model")],
            selected_model="main-model",
        )
        install_chat_session_routes(child)
        chats.append(child)
    for chat in chats:
        chat.update_session(labels={"omnigent.ui": "terminal"})
    primary.contract.json("/v1/sessions", list_payload([chat._session() for chat in chats]))
    primary.contract.json(
        "/health",
        {
            "sessions": {
                chat.session_id: {"runner_online": True, "host_online": True} for chat in chats
            }
        },
    )
    calls = []
    for chat in chats:

        def suggestion(route: Route, _request, *, session_id=chat.session_id) -> None:
            calls.append(session_id)
            route.fulfill(json={"status": "ready", "text": f"Review {session_id}."})

        primary.contract.route(
            re.compile(rf"/v1/sessions/{chat.session_id}/next-reply$"), suggestion
        )
    enable(page)
    page.set_viewport_size({"width": 1800, "height": 1000})
    try:
        page.goto(primary.url + "?panes=" + ",".join(chat.session_id for chat in chats[1:]))
        for chat in chats:
            pane = page.locator(f'section[data-pane-id="{chat.session_id}"]')
            composer = pane.get_by_test_id("side-chat-input")
            expect(composer).to_be_visible()
            composer.click()
            chat.wait_for_stream()
            finish(chat, f"turn-{chat.session_id}")
            expect(composer).to_have_attribute("placeholder", f"Review {chat.session_id}.")
            expect(composer).to_have_value("")
            composer.press("ArrowRight")
            expect(composer).to_have_value(f"Review {chat.session_id}.")
            assert chat.event_posts == []
        assert calls == [chat.session_id for chat in chats]
        page.screenshot(path=str(tmp_path / "three-pane-editable-drafts.png"), full_page=True)
        # Returning to a handled turn neither resurrects text nor repeats inference.
        for chat in chats:
            composer = page.locator(f'section[data-pane-id="{chat.session_id}"]').get_by_test_id(
                "side-chat-input"
            )
            composer.fill("")
            expect(composer).to_have_attribute("placeholder", "Message this chat...")
        page.wait_for_timeout(900)
        assert len(calls) == 3
        # A completed turn in another visible pane must not spend a request on focus.
        finish(chats[0], "inactive-turn")
        page.wait_for_timeout(900)
        first_input = page.locator(
            f'section[data-pane-id="{chats[0].session_id}"]'
        ).get_by_test_id("side-chat-input")
        first_input.click()
        page.wait_for_timeout(900)
        assert len(calls) == 3
        # The terminal surface is never an eligible composer, including on return.
        toolbar = page.get_by_test_id("active-pane-toolbar")
        toolbar.get_by_role("button", name="Terminal view", exact=True).click()
        expect(first_input).to_be_hidden()
        finish(chats[0], "terminal-turn")
        page.wait_for_timeout(900)
        toolbar.get_by_role("button", name="Chat view", exact=True).click()
        expect(first_input).to_be_visible()
        page.wait_for_timeout(900)
        assert len(calls) == 3
        assert not primary.contract.violations, primary.contract.violations
    finally:
        for stream in streams:
            stream.close()


def test_draft_race_disable_and_unsupported_runner_leave_typing_usable(
    page: Page, chat_session_contract, tmp_path
) -> None:
    chat = chat_session_contract
    chat.set_catalog(
        harness="claude-native", models=[model_option("main-model")], selected_model="main-model"
    )
    enable(page)
    held, cancelled = [], []
    url = rf"/v1/sessions/{chat.session_id}/next-reply"
    chat.contract.route(re.compile(url + "$"), lambda route: held.append(route))
    chat.contract.route(
        re.compile(url + "/[^/]+$"),
        lambda route: (
            cancelled.append(route.request.method),
            route.fulfill(json={"cancelled": True}),
        ),
    )
    page.goto(chat.url)
    chat.wait_for_stream()
    composer = page.get_by_role("textbox", name="Message the agent", exact=True)
    composer.click()
    with page.expect_request(
        lambda request: request.method == "POST" and request.url.endswith("/next-reply")
    ):
        finish(chat, "draft-race")
    composer.fill("Keep my own draft")
    page.wait_for_timeout(150)
    expect(composer).to_have_value("Keep my own draft")
    assert cancelled == ["DELETE"]
    # Drain the held transport after cancellation; never leave browser teardown pending.
    for route in held:
        with suppress(PlaywrightError):
            route.fulfill(json={"status": "ready", "text": "Discard this late reply."})
    expect(composer).to_have_value("Keep my own draft")
    # The next eligible turn receives an old-runner response, with no automatic retry.
    chat.contract.route(
        re.compile(url + "$"),
        lambda route: route.fulfill(status=404, json={"detail": "Not found"}),
    )
    composer.fill("")
    finish(chat, "old-runner")
    page.wait_for_timeout(1000)
    expect(composer).to_have_value("")
    expect(composer).to_have_attribute("placeholder", "Send a message…")
    # A same-account preference update cancels eligibility before another completed turn.
    page.evaluate(
        "localStorage.setItem('omnigent:reply-suggestions:local', 'off'); "
        "window.dispatchEvent(new Event('omnigent:reply-suggestions-change'))"
    )
    finish(chat, "disabled")
    page.wait_for_timeout(900)
    composer.fill("Typing still works")
    expect(composer).to_have_value("Typing still works")
    assert chat.event_posts == []
    page.screenshot(path=str(tmp_path / "draft-race-and-disablement.png"), full_page=True)
    assert not chat.contract.violations, chat.contract.violations


@pytest.mark.parametrize("reason", ["read-only", "hidden"])
def test_ineligible_browser_surfaces_never_request_a_reply(
    page: Page, chat_session_contract, reason
) -> None:
    chat = chat_session_contract
    chat.set_catalog(
        harness="codex-native", models=[model_option("main-model")], selected_model="main-model"
    )
    if reason == "read-only":
        chat._session_updates["permission_level"] = 1
    calls = []
    chat.contract.route(
        re.compile(rf"/v1/sessions/{chat.session_id}/next-reply$"),
        lambda route: (calls.append(route.request), route.fulfill(json={"status": "none"})),
    )
    enable(page)
    page.goto(chat.url)
    chat.wait_for_stream()
    if reason == "hidden":
        composer = page.get_by_role("textbox", name="Message the agent", exact=True)
        composer.click()
        page.evaluate(
            "Object.defineProperty(document, 'visibilityState', "
            "{configurable:true, value:'hidden'}); "
            "document.dispatchEvent(new Event('visibilitychange'))"
        )
    finish(chat, "ineligible")
    page.wait_for_timeout(1000)
    if reason == "hidden":
        page.evaluate(
            "Object.defineProperty(document, 'visibilityState', "
            "{configurable:true, value:'visible'}); "
            "document.dispatchEvent(new Event('visibilitychange'))"
        )
        composer.click()
        page.wait_for_timeout(900)
    assert calls == []
    assert chat.event_posts == []
    assert not chat.contract.violations, chat.contract.violations
