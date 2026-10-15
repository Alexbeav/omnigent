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
    add_pane = page.get_by_role("combobox", name="Add chat pane")
    assert add_pane.evaluate("element => element.closest('header') !== null")
    header_box = page.get_by_role("region", name="Primary chat").locator("header").bounding_box()
    add_box = add_pane.bounding_box()
    assert header_box is not None and add_box is not None
    assert add_box["y"] + add_box["height"] <= header_box["y"] + header_box["height"]

    source = page.locator(f'[data-sidebar-session-id="{secondary_ids[0]}"]').bounding_box()
    assert source is not None
    page_count = len(page.context.pages)
    page.mouse.move(source["x"] + 70, source["y"] + source["height"] / 2)
    page.mouse.down()
    page.mouse.move(source["x"] + 85, source["y"] + source["height"] / 2, steps=3)
    right_target = page.get_by_test_id(f"chat-split-{chat.session_id}-right")
    expect(right_target).to_be_visible()
    right_edge = right_target.bounding_box()
    assert right_edge is not None
    page.mouse.move(
        right_edge["x"] + right_edge["width"] / 2,
        right_edge["y"] + 200,
        steps=8,
    )
    page.mouse.up()
    ordered_panes = page.locator("section[data-pane-id]")
    expect(ordered_panes).to_have_count(2)
    assert ordered_panes.evaluate_all("panes => panes.map(pane => pane.dataset.paneId)") == [
        chat.session_id,
        secondary_ids[0],
    ]
    assert len(page.context.pages) == page_count

    source = page.locator(f'[data-sidebar-session-id="{secondary_ids[0]}"]').bounding_box()
    assert source is not None
    page.mouse.move(source["x"] + 70, source["y"] + source["height"] / 2)
    page.mouse.down()
    page.mouse.move(source["x"] + 85, source["y"] + source["height"] / 2, steps=3)
    left_target = page.get_by_test_id(f"chat-split-{chat.session_id}-left")
    expect(left_target).to_be_visible()
    left_edge = left_target.bounding_box()
    assert left_edge is not None
    page.mouse.move(left_edge["x"] + left_edge["width"] / 2, left_edge["y"] + 200, steps=8)
    page.mouse.up()
    expect(ordered_panes.first).to_have_attribute("data-pane-id", secondary_ids[0])
    assert ordered_panes.evaluate_all("panes => panes.map(pane => pane.dataset.paneId)") == [
        secondary_ids[0],
        chat.session_id,
    ]

    source = page.locator(f'[data-sidebar-session-id="{secondary_ids[1]}"]').bounding_box()
    assert source is not None
    page.mouse.move(source["x"] + 70, source["y"] + source["height"] / 2)
    page.mouse.down()
    page.mouse.move(source["x"] + 85, source["y"] + source["height"] / 2, steps=3)
    target = page.get_by_test_id(f"chat-split-{chat.session_id}-right")
    expect(target).to_be_visible()
    edge = target.bounding_box()
    assert edge is not None
    page.mouse.move(edge["x"] + edge["width"] / 2, edge["y"] + 200, steps=8)
    page.mouse.up()
    expect(ordered_panes).to_have_count(3)
    assert ordered_panes.evaluate_all("panes => panes.map(pane => pane.dataset.paneId)") == [
        secondary_ids[0],
        chat.session_id,
        secondary_ids[1],
    ]

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
        re.compile(
            rf"{re.escape(chat.contract.base_url)}/c/(?:{chat.session_id}|{secondary_ids[0]}|{secondary_ids[1]})$"
        ),
        lambda route: route.fulfill(
            content_type="text/html", body="<title>Popout verification</title>"
        ),
    )
    primary_header = (
        page.get_by_role("region", name="Primary chat").locator("header").bounding_box()
    )
    assert primary_header is not None
    page_count = len(page.context.pages)
    page.mouse.move(primary_header["x"] + 200, primary_header["y"] + 4)
    page.mouse.down()
    page.mouse.move(primary_header["x"] + 220, primary_header["y"] + 4)
    expect(page.get_by_test_id("chat-detach-target")).to_be_visible()
    page.keyboard.press("Escape")
    page.mouse.move(1620, 200)
    page.mouse.up()
    expect(page.get_by_test_id("chat-detach-target")).to_be_hidden()
    assert len(page.context.pages) == page_count

    with page.context.expect_page() as primary_opened:
        page.mouse.move(
            primary_header["x"] + 200,
            primary_header["y"] + 4,
        )
        page.mouse.down()
        page.mouse.move(
            primary_header["x"] + 220,
            primary_header["y"] + 4,
        )
        expect(page.get_by_test_id("chat-detach-target")).to_be_visible()
        # CDP still delivers this captured pointer release just beyond Chromium's viewport.
        page.mouse.move(1620, 200, steps=8)
        page.mouse.up()
    primary_popout = primary_opened.value
    expect(primary_popout).to_have_title("Popout verification")
    assert urlparse(primary_popout.url).path == f"/c/{chat.session_id}"
    assert primary_popout.evaluate("window.opener === null")
    primary_popout.close()

    pane_three = page.get_by_role("region", name="Chat: Browser pane 3")
    header = pane_three.locator("header").bounding_box()
    assert header is not None
    with page.context.expect_page() as opened:
        page.mouse.move(header["x"] + 80, header["y"] + header["height"] / 2)
        page.mouse.down()
        page.mouse.move(header["x"] + 100, header["y"] + header["height"] / 2, steps=3)
        detach = page.get_by_test_id("chat-detach-target")
        expect(detach).to_be_visible()
        detach_box = detach.bounding_box()
        assert detach_box is not None
        page.mouse.move(detach_box["x"] + 10, detach_box["y"] + 200, steps=8)
        page.mouse.up()
    popout = opened.value
    expect(popout).to_have_title("Popout verification")
    assert urlparse(popout.url).path == f"/c/{secondary_ids[1]}"
    assert popout.evaluate("window.opener === null")
    popout.close()

    sidebar_source = page.locator(f'[data-sidebar-session-id="{secondary_ids[0]}"]').bounding_box()
    assert sidebar_source is not None
    page_count = len(page.context.pages)
    page.mouse.move(sidebar_source["x"] + 70, sidebar_source["y"] + sidebar_source["height"] / 2)
    page.mouse.down()
    page.mouse.move(
        sidebar_source["x"] + 85,
        sidebar_source["y"] + sidebar_source["height"] / 2,
        steps=3,
    )
    expect(page.get_by_text("Drop to open in new window", exact=True)).to_be_visible()
    page.keyboard.press("Escape")
    page.mouse.up()
    expect(page.get_by_text("Drop to open in new window", exact=True)).to_be_hidden()
    assert len(page.context.pages) == page_count
    page.wait_for_timeout(100)
    sidebar_source = page.locator(f'[data-sidebar-session-id="{secondary_ids[0]}"]').bounding_box()
    assert sidebar_source is not None

    with page.context.expect_page() as sidebar_opened:
        page.mouse.move(
            sidebar_source["x"] + 70, sidebar_source["y"] + sidebar_source["height"] / 2
        )
        page.mouse.down()
        page.mouse.move(
            sidebar_source["x"] + 85,
            sidebar_source["y"] + sidebar_source["height"] / 2,
            steps=3,
        )
        sidebar_detach = page.get_by_text("Drop to open in new window", exact=True)
        expect(sidebar_detach).to_be_visible()
        sidebar_detach_box = sidebar_detach.bounding_box()
        assert sidebar_detach_box is not None
        page.mouse.move(sidebar_detach_box["x"] + 10, sidebar_detach_box["y"] + 250, steps=8)
        page.mouse.up()
    sidebar_popout = sidebar_opened.value
    expect(sidebar_popout).to_have_title("Popout verification")
    assert urlparse(sidebar_popout.url).path == f"/c/{secondary_ids[0]}"
    assert sidebar_popout.evaluate("window.opener === null")
    sidebar_popout.close()

    page.get_by_role("button", name="Close Browser pane 3 pane").click()
    expect(panes).to_have_count(2)
    page.get_by_role("combobox", name="Add chat pane").select_option(secondary_ids[1])
    expect(third).to_have_value("Draft for the third chat")

    page.set_viewport_size({"width": 390, "height": 844})
    expect(page.get_by_role("region", name="Chat: Browser pane 2")).to_be_hidden()
    expect(page.get_by_role("region", name="Chat: Browser pane 3")).to_be_hidden()
    expect(page.get_by_role("region", name="Primary chat")).to_be_visible()

    assert not chat.contract.violations, chat.contract.violations
