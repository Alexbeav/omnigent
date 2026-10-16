"""Configuration changes in a pane must stay on that pane's conversation."""

import json
import re

from playwright.sync_api import Page, Route, expect

from tests.browser_ui.chat.session_contract import (
    _ChatSseStream,
    list_payload,
    model_option,
    session_status_event,
)


def test_each_pane_changes_its_own_model_effort_and_permissions(
    page: Page, chat_session_contract, tmp_path
) -> None:
    chat = chat_session_contract
    chat.set_catalog(
        harness="codex-native",
        models=[model_option("primary-model", display_name="Primary model")],
        selected_model="primary-model",
    )
    chat.update_session(labels={"omnigent.wrapper": "codex-native-ui"})
    chat.contract.json(f"/v1/sessions/{chat.session_id}/codex_goal", {"goal": None})
    rows = [chat._session()]
    changes = []
    for vendor in ("codex", "claude"):
        session_id = f"pane-{vendor}"
        models = [
            {
                **model_option(
                    f"{vendor}-{suffix}", display_name=f"{vendor.title()} model {suffix}"
                ),
                "supportedReasoningEfforts": [
                    {"reasoningEffort": effort} for effort in ("low", "medium", "high")
                ],
            }
            for suffix in ("a", "b")
        ]
        wrapper = "claude-code-native-ui" if vendor == "claude" else "codex-native-ui"
        row = {
            **chat._session(),
            "id": session_id,
            "title": f"{vendor.title()} pane",
            "harness": f"{vendor}-native",
            "labels": {"omnigent.wrapper": wrapper},
            "model_options": models,
            "llm_model": f"{vendor}-a",
            "reasoning_effort": "high",
        }
        rows.append(row)

        def make_session_route(row, vendor):
            def session_route(route: Route) -> None:
                if route.request.method == "PATCH":
                    body = route.request.post_data_json
                    changes.append((row["id"], body))
                    row.update(body)
                    if "model_override" in body:
                        row["llm_model"] = body["model_override"]
                    for field in ("permission_mode", "approval_mode"):
                        if field in body:
                            row["labels"][f"omnigent.{vendor}_native.{field}"] = body[field]
                route.fulfill(content_type="application/json", body=json.dumps(row))

            return session_route

        chat.contract.route(
            re.compile(rf"{re.escape(chat.base_url)}/v1/sessions/{session_id}(?:\?.*)?$"),
            make_session_route(row, vendor),
        )
        chat.contract.json(f"/v1/sessions/{session_id}/items", list_payload([]))
        chat.contract.json(f"/v1/sessions/{session_id}/child_sessions", list_payload([]))
        chat.contract.sse(f"/v1/sessions/{session_id}/stream")

    chat.contract.json("/v1/sessions", list_payload(rows))
    page.set_viewport_size({"width": 1600, "height": 1000})
    page.goto(chat.url + "?panes=pane-codex,pane-claude")
    primary = page.get_by_role("region", name="Primary chat")
    primary.get_by_placeholder("Send a message…").fill("Keep the primary draft")

    for vendor in ("codex", "claude"):
        pane = page.get_by_role("region", name=f"Chat: {vendor.title()} pane")
        pane.get_by_test_id("side-chat-input").fill(f"Keep the {vendor} draft")
        expect(pane.get_by_test_id("composer-config-gear")).to_be_visible()
        expect(pane.get_by_test_id("composer-host-icon")).to_be_visible()
        pane.get_by_test_id("composer-permission-chip").click()
        mode = "full-access" if vendor == "codex" else "auto"
        page.get_by_test_id(f"composer-permission-option-{mode}").click()
        pane.get_by_test_id("composer-config-gear").click()
        page.get_by_test_id("composer-agent-edit").click()
        page.get_by_test_id("composer-agent-effort-low").click()
        expect(page.get_by_test_id("composer-agent-effort-low")).to_be_checked()
        page.get_by_test_id(f"composer-agent-model-{vendor}-b").click()
        page.keyboard.press("Escape")
        page.keyboard.press("Escape")
        expect(page.get_by_test_id("composer-agent-menu")).to_have_count(0)
        expect(primary.get_by_placeholder("Send a message…")).to_have_value(
            "Keep the primary draft"
        )
        expect(pane.get_by_test_id("side-chat-input")).to_have_value(f"Keep the {vendor} draft")

    assert changes == [
        ("pane-codex", {"approval_mode": "full-access"}),
        ("pane-codex", {"reasoning_effort": "low"}),
        ("pane-codex", {"model_override": "codex-b"}),
        ("pane-claude", {"permission_mode": "auto"}),
        ("pane-claude", {"reasoning_effort": "low"}),
        ("pane-claude", {"model_override": "claude-b"}),
    ]
    assert not chat.session_patches
    page.reload()
    for vendor in ("codex", "claude"):
        pane = page.get_by_role("region", name=f"Chat: {vendor.title()} pane")
        expect(pane.get_by_test_id("composer-agent-config-value")).to_contain_text(
            f"{vendor.title()} model b"
        )
        pane.get_by_test_id("composer-config-gear").click()
        page.get_by_test_id("composer-agent-edit").click()
        expect(page.get_by_test_id("composer-agent-effort-low")).to_be_checked()
        page.keyboard.press("Escape")
        page.keyboard.press("Escape")
        expect(page.get_by_test_id("composer-agent-menu")).to_have_count(0)
    expect(primary.get_by_test_id("composer-agent-config-value")).to_contain_text("Primary model")
    page.screenshot(path=str(tmp_path / "pane-session-controls.png"), full_page=True)
    assert not chat.contract.violations, chat.contract.violations


def test_secondary_pane_queue_and_steer_stay_on_that_session(
    page: Page, chat_session_contract, tmp_path
) -> None:
    chat = chat_session_contract
    secondary_id = "pane-queue-steer"
    secondary_stream = _ChatSseStream()
    secondary_posts: list[dict] = []
    secondary = {
        **chat._session(),
        "id": secondary_id,
        "title": "Queue and steer pane",
        "status": "idle",  # Deliberately stale while the pane SSE is busy.
        "harness": "claude-native",
        "labels": {"omnigent.wrapper": "claude-code-native-ui"},
    }

    def stream(route: Route) -> None:
        if route.request.method != "GET":
            route.fallback()
            return
        route.continue_(url=secondary_stream.url)

    def post_event(route: Route) -> None:
        if route.request.method != "POST":
            route.fallback()
            return
        secondary_posts.append(route.request.post_data_json)
        route.fulfill(json={"queued": True, "item_id": f"secondary-{len(secondary_posts)}"})

    def posted_texts() -> list[str]:
        return [
            block["text"]
            for post in secondary_posts
            for block in post["data"]["content"]
            if block.get("type") == "input_text"
        ]

    session_url = re.escape(f"{chat.base_url}/v1/sessions/{secondary_id}")
    chat.contract.json("/v1/sessions", list_payload([chat._session(), secondary]))
    chat.contract.json(
        "/health",
        {
            "sessions": {
                chat.session_id: {"runner_online": True, "host_online": True},
                secondary_id: {"runner_online": True, "host_online": True},
            }
        },
    )
    chat.contract.json(f"/v1/sessions/{secondary_id}", secondary)
    chat.contract.json(f"/v1/sessions/{secondary_id}/items", list_payload([]))
    chat.contract.json(f"/v1/sessions/{secondary_id}/child_sessions", list_payload([]))
    chat.contract.route(re.compile(rf"^{session_url}/stream(?:\?.*)?$"), stream)
    chat.contract.route(re.compile(rf"^{session_url}/events(?:\?.*)?$"), post_event)

    try:
        secondary_stream.emit(session_status_event(secondary_id, "running", response_id="busy"))
        page.set_viewport_size({"width": 1400, "height": 900})
        page.goto(chat.url + f"?panes={secondary_id}")
        pane = page.get_by_role("region", name="Chat: Queue and steer pane")
        primary = page.get_by_role("region", name="Primary chat").get_by_placeholder(
            "Send a message…"
        )
        primary.fill("Primary draft must remain")
        composer = pane.get_by_test_id("side-chat-input")

        composer.fill("Edit this queued message")
        expect(pane.get_by_role("button", name="Queue message")).to_be_visible()
        composer.press("Enter")
        page.wait_for_timeout(350)
        assert secondary_posts == []
        assert chat.event_posts == []

        strip = pane.get_by_test_id("composer-queued-strip")
        strip.get_by_role("button", name="Edit queued message", exact=True).click()
        expect(composer).to_have_value("Edit this queued message")
        composer.fill("Edited queued message")
        composer.press("Enter")
        composer.fill("Delete this queued message")
        composer.press("Enter")
        strip.get_by_role("button", name="Remove queued message", exact=True).last.click()
        expect(strip.get_by_text("Delete this queued message", exact=True)).to_have_count(0)
        assert secondary_posts == []

        with page.expect_request(
            lambda request: (
                request.method == "POST"
                and request.url.endswith(f"/v1/sessions/{secondary_id}/events")
            )
        ):
            strip.get_by_role("button", name="Send queued message now", exact=True).click()
        assert posted_texts() == ["Edited queued message"]
        assert chat.event_posts == []

        composer.fill("Flush only after idle")
        composer.press("Enter")
        page.wait_for_timeout(350)
        assert posted_texts() == ["Edited queued message"]
        with page.expect_request(
            lambda request: (
                request.method == "POST"
                and request.url.endswith(f"/v1/sessions/{secondary_id}/events")
            )
        ):
            secondary_stream.emit(session_status_event(secondary_id, "idle", response_id="busy"))
        for _ in range(50):
            if len(secondary_posts) == 2:
                break
            page.wait_for_timeout(20)
        assert posted_texts() == ["Edited queued message", "Flush only after idle"]

        secondary_stream.emit(
            session_status_event(secondary_id, "running", response_id="steer-all")
        )
        composer.fill("First steer-all message")
        expect(pane.get_by_role("button", name="Queue message")).to_be_visible()
        composer.press("Enter")
        composer.fill("Second steer-all message")
        composer.press("Control+Enter")
        for _ in range(50):
            if len(secondary_posts) == 4:
                break
            page.wait_for_timeout(20)
        assert posted_texts() == [
            "Edited queued message",
            "Flush only after idle",
            "First steer-all message",
            "Second steer-all message",
        ]
        assert chat.event_posts == []
        expect(primary).to_have_value("Primary draft must remain")
        expect(strip).to_have_count(0)
        page.screenshot(path=str(tmp_path / "pane-queue-steer.png"), full_page=True)
        assert not chat.contract.violations, chat.contract.violations
    finally:
        secondary_stream.close()
