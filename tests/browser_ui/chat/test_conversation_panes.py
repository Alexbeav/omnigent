"""Browser proof for the desktop multi-chat layout."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Page, expect

from tests.browser_ui.chat.session_contract import (
    ChatSessionContract,
    install_chat_session_routes,
    list_payload,
)


def test_three_chat_columns_resize_independently(
    page: Page,
    chat_session_contract: ChatSessionContract,
    tmp_path,
) -> None:
    chat = chat_session_contract
    install_chat_session_routes(
        ChatSessionContract(page, chat.contract, chat.stream, session_id="browser-pane-five")
    )
    secondary_ids = ("browser-pane-two", "browser-pane-three")
    rows = [chat._session()]
    for index, session_id in enumerate(
        (*secondary_ids, "browser-pane-four", "browser-pane-five"), start=2
    ):
        install_chat_session_routes(
            ChatSessionContract(page, chat.contract, chat.stream, session_id=session_id)
        )
        row = {**chat._session(), "id": session_id, "title": f"Browser pane {index}"}
        rows.append(row)
        chat.contract.json(f"/v1/sessions/{session_id}", row)
        chat.contract.json(f"/v1/sessions/{session_id}/items", list_payload([]))
        chat.contract.json(f"/v1/sessions/{session_id}/child_sessions", list_payload([]))
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
    header_box = (
        page.locator(f'section[data-pane-id="{chat.session_id}"]').locator("header").bounding_box()
    )
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
    primary_box = page.locator(f'section[data-pane-id="{chat.session_id}"]').bounding_box()
    assert primary_box is not None
    assert abs(right_edge["width"] - primary_box["width"] / 2) <= 1
    assert (
        abs(right_edge["x"] + right_edge["width"] - primary_box["x"] - primary_box["width"]) <= 1
    )
    expect(page.get_by_text("Drop to open in new window", exact=True)).to_have_count(0)
    page.mouse.move(
        right_edge["x"] + right_edge["width"] / 2,
        right_edge["y"] + 200,
        steps=8,
    )
    expect(right_target).to_have_attribute("data-active", "true")
    expect(page.get_by_test_id("chat-split-preview")).to_contain_text("Open in split view")
    page.screenshot(path=str(tmp_path / "split-preview-right.png"))
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
    expect(left_target).to_have_attribute("data-active", "true")
    expect(page.get_by_test_id("chat-split-preview")).to_contain_text("Split view")
    page.screenshot(path=str(tmp_path / "split-preview-left.png"))
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

    expect(
        page.locator(f'section[data-pane-id="{chat.session_id}"]').get_by_role("separator")
    ).to_be_visible()
    panes = page.locator("[data-testid=conversation-panes] > section")
    expect(panes).to_have_count(3)
    expect(page.locator(f'section[data-pane-id="{secondary_ids[0]}"]')).to_be_visible()
    expect(page.locator(f'section[data-pane-id="{secondary_ids[1]}"]')).to_be_visible()
    primary = page.locator(f'section[data-pane-id="{chat.session_id}"]').get_by_test_id(
        "side-chat-input"
    )
    second = page.locator(f'section[data-pane-id="{secondary_ids[0]}"]').get_by_test_id(
        "side-chat-input"
    )
    third = page.locator(f'section[data-pane-id="{secondary_ids[1]}"]').get_by_test_id(
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

    def resize_boundaries() -> None:
        expect(ordered_panes.first.get_by_role("separator")).to_have_count(0)
        for index in (1, 2):
            handle = ordered_panes.nth(index).get_by_role("separator")
            expect(handle).to_be_visible()
            before = ordered_panes.evaluate_all(
                "panes => panes.map(pane => pane.getBoundingClientRect().width)"
            )
            handle.press("ArrowLeft")
            after = ordered_panes.evaluate_all(
                "panes => panes.map(pane => pane.getBoundingClientRect().width)"
            )
            for slot in range(3):
                delta = -20 if slot == index - 1 else 20 if slot == index else 0
                assert abs(after[slot] - before[slot] - delta) <= 2
            separator = handle.bounding_box()
            assert separator is not None
            page.mouse.move(separator["x"] + 2, separator["y"] + 150)
            page.mouse.down()
            page.mouse.move(separator["x"] + 17, separator["y"] + 150, steps=5)
            page.mouse.up()
            dragged = ordered_panes.evaluate_all(
                "panes => panes.map(pane => pane.getBoundingClientRect().width)"
            )
            for slot in range(3):
                delta = 15 if slot == index - 1 else -15 if slot == index else 0
                assert abs(dragged[slot] - after[slot] - delta) <= 2

    resize_boundaries()
    assert set(parse_qs(urlparse(page.url).query)["panes"][0].split(",")) == {
        chat.session_id,
        secondary_ids[0],
    }
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
        page.locator(f'section[data-pane-id="{chat.session_id}"]').locator("header").bounding_box()
    )
    assert primary_header is not None
    page_count = len(page.context.pages)
    page.mouse.move(primary_header["x"] + 200, primary_header["y"] + 4)
    page.mouse.down()
    page.mouse.move(primary_header["x"] + 220, primary_header["y"] + 4)
    expect(page.get_by_test_id("chat-detach-target")).to_have_count(0)
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
        expect(page.get_by_test_id("chat-detach-target")).to_have_count(0)
        # CDP still delivers this captured pointer release just beyond Chromium's viewport.
        page.mouse.move(1620, 200, steps=8)
        page.mouse.up()
    primary_popout = primary_opened.value
    expect(primary_popout).to_have_title("Popout verification")
    assert urlparse(primary_popout.url).path == f"/c/{chat.session_id}"
    assert primary_popout.evaluate("window.opener === null")
    primary_popout.close()

    pane_three = page.locator(f'section[data-pane-id="{secondary_ids[1]}"]')
    header = pane_three.locator("header").bounding_box()
    assert header is not None
    with page.context.expect_page() as opened:
        page.mouse.move(header["x"] + 80, header["y"] + header["height"] / 2)
        page.mouse.down()
        page.mouse.move(header["x"] + 100, header["y"] + header["height"] / 2, steps=3)
        expect(page.get_by_test_id("chat-detach-target")).to_have_count(0)
        page.mouse.move(1620, 200, steps=8)
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
    expect(page.get_by_text("Drop to open in new window", exact=True)).to_have_count(0)
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
        expect(page.get_by_text("Drop to open in new window", exact=True)).to_have_count(0)
        page.mouse.move(1620, 250, steps=8)
        page.mouse.up()
    sidebar_popout = sidebar_opened.value
    expect(sidebar_popout).to_have_title("Popout verification")
    assert urlparse(sidebar_popout.url).path == f"/c/{secondary_ids[0]}"
    assert sidebar_popout.evaluate("window.opener === null")
    sidebar_popout.close()

    source = page.locator('[data-sidebar-session-id="browser-pane-four"]').bounding_box()
    assert source is not None
    page.mouse.move(source["x"] + 70, source["y"] + source["height"] / 2)
    page.mouse.down()
    page.mouse.move(source["x"] + 85, source["y"] + source["height"] / 2, steps=3)
    expect(page.locator('[data-testid^="chat-split-"]')).to_have_count(0)
    page.mouse.move(1599, 250, steps=8)
    page.mouse.up()
    expect(ordered_panes).to_have_count(3)
    assert len(page.context.pages) == page_count

    # A sidebar choice replaces only the active pane; existing chats are focused.
    second.fill("Draft retained in the other pane")
    third.click()
    expect(pane_three).to_have_attribute("data-active-pane", "true")
    page.get_by_role("link", name="Browser pane 4", exact=True).click()
    expect(ordered_panes).to_have_count(3)
    expect(ordered_panes.last).to_have_attribute("data-pane-id", "browser-pane-four")
    expect(ordered_panes.last).to_have_attribute("data-active-pane", "true")
    assert urlparse(page.url).path == "/c/browser-pane-four"
    expect(primary).to_have_value("Draft for the first chat")
    expect(second).to_have_value("Draft retained in the other pane")
    page.get_by_role("link", name="Browser pane 2", exact=True).click()
    expect(ordered_panes.first).to_have_attribute("data-active-pane", "true")
    expect(ordered_panes).to_have_count(3)
    retained_width = ordered_panes.first.bounding_box()["width"]
    page.get_by_role("link", name="Browser pane 5", exact=True).click()
    expect(ordered_panes.first).to_have_attribute("data-pane-id", "browser-pane-five")
    assert abs(ordered_panes.first.bounding_box()["width"] - retained_width) <= 1
    page.get_by_role("link", name="Browser pane 2", exact=True).click()
    expect(second).to_have_value("Draft retained in the other pane")
    assert abs(ordered_panes.first.bounding_box()["width"] - retained_width) <= 1

    primary.click()
    page.get_by_role("link", name="Browser pane 5", exact=True).click()
    expect(page.locator('section[data-pane-id="browser-pane-five"]')).to_have_attribute(
        "data-active-pane", "true"
    )
    assert urlparse(page.url).path == "/c/browser-pane-five"
    expect(ordered_panes.first).to_have_attribute("data-pane-id", secondary_ids[0])
    expect(ordered_panes.last).to_have_attribute("data-pane-id", "browser-pane-four")
    expect(second).to_have_value("Draft retained in the other pane")
    page.get_by_role("link", name=rows[0]["title"], exact=True).click()
    expect(primary).to_have_value("Draft for the first chat")
    expect(ordered_panes).to_have_count(3)
    page.locator('section[data-pane-id="browser-pane-four"]').get_by_test_id(
        "side-chat-input"
    ).click()
    page.get_by_role("link", name="Browser pane 3", exact=True).click()
    expect(third).to_have_value("Draft for the third chat")
    expect(ordered_panes.last).to_have_attribute("data-active-pane", "true")
    page.screenshot(path=str(tmp_path / "active-pane-replacement.png"))

    page.get_by_role("button", name="Close Browser pane 3 pane").click()
    expect(panes).to_have_count(2)
    page.get_by_role("combobox", name="Add chat pane").select_option(secondary_ids[1])
    expect(third).to_have_value("Draft for the third chat")

    source = page.locator(f'[data-sidebar-session-id="{chat.session_id}"]').bounding_box()
    assert source is not None
    page.mouse.move(source["x"] + 70, source["y"] + source["height"] / 2)
    page.mouse.down()
    page.mouse.move(source["x"] + 85, source["y"] + source["height"] / 2, steps=3)
    target = page.get_by_test_id(f"chat-split-{secondary_ids[0]}-left").bounding_box()
    assert target is not None
    page.mouse.move(target["x"] + target["width"] / 2, target["y"] + 200, steps=8)
    page.mouse.up()
    expect(ordered_panes.first).to_have_attribute("data-pane-id", chat.session_id)
    assert abs(ordered_panes.first.bounding_box()["width"] - retained_width) <= 1
    resize_boundaries()

    source = page.locator(f'[data-sidebar-session-id="{chat.session_id}"]').bounding_box()
    assert source is not None
    page.mouse.move(source["x"] + 70, source["y"] + source["height"] / 2)
    page.mouse.down()
    page.mouse.move(source["x"] + 85, source["y"] + source["height"] / 2, steps=3)
    target = page.get_by_test_id(f"chat-split-{secondary_ids[1]}-right").bounding_box()
    assert target is not None
    page.mouse.move(target["x"] + target["width"] / 2, target["y"] + 200, steps=8)
    page.mouse.up()
    expect(ordered_panes.last).to_have_attribute("data-pane-id", chat.session_id)
    resize_boundaries()

    page.set_viewport_size({"width": 390, "height": 844})
    expect(page.locator(f'section[data-pane-id="{secondary_ids[0]}"]')).to_be_hidden()
    expect(page.locator(f'section[data-pane-id="{secondary_ids[1]}"]')).to_be_hidden()
    expect(page.locator(f'section[data-pane-id="{chat.session_id}"]')).to_be_visible()
    assert (
        page.locator(f'section[data-pane-id="{chat.session_id}"]').bounding_box()["width"] <= 390
    )

    assert not chat.contract.violations, chat.contract.violations
