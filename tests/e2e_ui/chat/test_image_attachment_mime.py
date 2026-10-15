"""Generic browser file types still reach the image send path through every input."""

from __future__ import annotations

import base64

import pytest
from playwright.sync_api import Page, expect

from tests.e2e_ui.start_session.test_image_only_first_message_send import _PNG_B64


@pytest.mark.parametrize("method", ["picker", "paste", "drop"])
@pytest.mark.parametrize("mime", ["", "application/octet-stream"])
def test_generic_image_type_sends_image_block(
    page: Page, seeded_session: tuple[str, str], method: str, mime: str
) -> None:
    base_url, session_id = seeded_session
    page.route(
        "**/events", lambda route: route.fulfill(json={"queued": True, "item_id": "image-proof"})
    )
    page.goto(f"{base_url}/c/{session_id}")
    composer = page.get_by_placeholder("Send a message…")
    expect(composer).to_be_visible(timeout=30_000)
    filename = "screenshot.png"
    if method == "picker":
        page.get_by_role("button", name="Add", exact=True).click()
        with page.expect_file_chooser() as chooser:
            page.get_by_text("Files and images", exact=True).click()
        chooser.value.set_files(
            {"name": filename, "mimeType": mime, "buffer": base64.b64decode(_PNG_B64)}
        )
    else:
        page.evaluate(
            """([method, name, mime, encoded]) => {
                const bytes = Uint8Array.from(atob(encoded), char => char.charCodeAt(0));
                const transfer = new DataTransfer();
                transfer.items.add(new File([bytes], name, {type: mime}));
                if (method === 'paste') {
                    document.querySelector('textarea[placeholder="Send a message…"]')
                        .dispatchEvent(new ClipboardEvent('paste', {
                            clipboardData: transfer, bubbles: true, cancelable: true,
                        }));
                } else {
                    const target = document.querySelector('[data-chat-surface]');
                    for (const type of ['dragenter', 'dragover', 'drop']) {
                        target.dispatchEvent(new DragEvent(type, {
                            dataTransfer: transfer, bubbles: true, cancelable: true,
                        }));
                    }
                }
            }""",
            [method, filename, mime, _PNG_B64],
        )
    expect(page.get_by_role("button", name=f"Remove {filename}")).to_be_visible()
    composer.fill("Inspect this screenshot.")
    with page.expect_request(
        lambda request: request.method == "POST" and request.url.endswith("/events")
    ) as sent:
        composer.press("Enter")
    content = sent.value.post_data_json["data"]["content"]
    images = [block for block in content if block["type"] == "input_image"]
    assert len(images) == 1 and images[0]["file_id"]
    assert not any(block["type"] == "input_file" for block in content)
