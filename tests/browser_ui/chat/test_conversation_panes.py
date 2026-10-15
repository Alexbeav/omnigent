"""Browser proof for the desktop multi-chat layout."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Page, expect

from tests.browser_ui.chat.session_contract import ChatSessionContract, list_payload


def test_three_chat_columns_resize_independently(
    page: Page,
    chat_session_contract: ChatSessionContract,
    tmp_path,
) -> None:
    chat = chat_session_contract
    secondary_ids = ("browser-pane-two", "browser-pane-three")
    rows = [chat._session()]
    for index, session_id in enumerate(secondary_ids, start=2):
        row = {**chat._session(), "id": session_id, "title": f"Browser pane {index}"}
        rows.append(row)
        chat.contract.json(f"/v1/sessions/{session_id}", row)
        chat.contract.json(f"/v1/sessions/{session_id}/items", list_payload([]))
        chat.contract.sse(f"/v1/sessions/{session_id}/stream")
        chat.contract.json(
            f"/v1/sessions/{session_id}/events",
            {"queued": True, "item_id": f"{session_id}-proof"},
            method="POST",
        )

    chat.contract.json("/v1/sessions", list_payload(rows))
    chat.contract.json(
        f"/v1/sessions/{chat.session_id}/child_sessions",
        list_payload(
            [
                {
                    "id": "browser-delegated-work",
                    "title": "Image attachment work",
                    "task_summary": None,
                    "tool": None,
                    "session_name": None,
                    "current_task_status": "in_progress",
                    "busy": True,
                    "pending_elicitations_count": 0,
                }
            ]
        ),
    )
    chat.contract.json("/v1/sessions/browser-delegated-work/child_sessions", list_payload([]))
    page.set_viewport_size({"width": 1600, "height": 900})
    page.goto(chat.url)
    expect(page.get_by_text("1 child chat", exact=True)).to_be_visible()
    expect(page.get_by_role("link", name="Image attachment work: Working")).to_have_attribute(
        "href", "/c/browser-delegated-work"
    )
    page.get_by_role("combobox", name="Add chat pane").select_option(secondary_ids[0])
    source = page.locator(f'[data-sidebar-session-id="{secondary_ids[1]}"]').bounding_box()
    assert source is not None
    page.mouse.move(source["x"] + 70, source["y"] + source["height"] / 2)
    page.mouse.down()
    page.mouse.move(source["x"] + 85, source["y"] + source["height"] / 2, steps=3)
    target = page.get_by_text("Drop to split chat", exact=True)
    expect(target).to_be_visible()
    edge = target.bounding_box()
    assert edge is not None
    page.mouse.move(edge["x"] + edge["width"] / 2, edge["y"] + 200, steps=8)
    page.mouse.up()

    panes = page.locator("[data-testid=conversation-panes] > section")
    expect(panes).to_have_count(3)
    expect(page.get_by_role("region", name="Chat: Browser pane 2")).to_be_visible()
    expect(page.get_by_role("region", name="Chat: Browser pane 3")).to_be_visible()
    primary = page.get_by_role("region", name="Primary chat").get_by_placeholder("Send a message…")
    second = page.get_by_role("region", name="Chat: Browser pane 2").get_by_test_id(
        "side-chat-input"
    )
    third = page.get_by_role("region", name="Chat: Browser pane 3").get_by_test_id(
        "side-chat-input"
    )
    primary.fill("Draft for the first chat")
    second.fill("Message for the second chat")
    third.fill("Draft for the third chat")
    expect(primary).to_have_value("Draft for the first chat")
    expect(third).to_have_value("Draft for the third chat")
    with page.expect_request(
        lambda request: (
            request.method == "POST" and request.url.endswith(f"/{secondary_ids[0]}/events")
        )
    ) as sent:
        second.press("Enter")
    content = sent.value.post_data_json["data"]["content"]
    assert any(block.get("text") == "Message for the second chat" for block in content)
    assert not chat.event_posts
    expect(primary).to_have_value("Draft for the first chat")
    expect(third).to_have_value("Draft for the third chat")
    before = page.get_by_role("region", name="Chat: Browser pane 2").bounding_box()
    assert before is not None

    page.get_by_role("separator", name="Resize Chat: Browser pane 2").press("ArrowLeft")
    after = page.get_by_role("region", name="Chat: Browser pane 2").bounding_box()
    assert after is not None and after["width"] > before["width"]
    separator = page.get_by_role("separator", name="Resize Chat: Browser pane 2").bounding_box()
    assert separator is not None
    page.mouse.move(separator["x"] + 2, separator["y"] + 150)
    page.mouse.down()
    page.mouse.move(separator["x"] - 30, separator["y"] + 150, steps=5)
    page.mouse.up()
    dragged = page.get_by_role("region", name="Chat: Browser pane 2").bounding_box()
    assert dragged is not None and dragged["width"] > after["width"]
    assert parse_qs(urlparse(page.url).query)["panes"] == [",".join(secondary_ids)]
    page.screenshot(path=str(tmp_path / "three-chat-columns.png"), full_page=True)

    chat.contract.route(
        re.compile(rf"{re.escape(chat.contract.base_url)}/c/{secondary_ids[1]}$"),
        lambda route: route.fulfill(
            content_type="text/html", body="<title>Popout verification</title>"
        ),
    )
    with page.context.expect_page() as opened:
        page.get_by_role("region", name="Chat: Browser pane 3").get_by_role(
            "button", name="Open Browser pane 3 in a new window"
        ).click()
    popout = opened.value
    expect(popout).to_have_title("Popout verification")
    assert urlparse(popout.url).path == f"/c/{secondary_ids[1]}"
    assert popout.evaluate("window.opener === null")
    popout.close()

    page.get_by_role("button", name="Close Browser pane 3 pane").click()
    expect(panes).to_have_count(2)
    page.get_by_role("combobox", name="Add chat pane").select_option(secondary_ids[1])
    expect(third).to_have_value("Draft for the third chat")

    page.set_viewport_size({"width": 390, "height": 844})
    expect(page.get_by_role("region", name="Chat: Browser pane 2")).to_be_hidden()
    expect(page.get_by_role("region", name="Chat: Browser pane 3")).to_be_hidden()
    expect(page.get_by_role("region", name="Primary chat")).to_be_visible()

    assert not chat.contract.violations, chat.contract.violations
