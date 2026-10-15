"""Provider request snapshots must never become conversation history."""

import json
from pathlib import Path

import pytest

from omnigent.harnesses.claude_native import bridge, main
from omnigent.inner import claude_native_executor
from omnigent.inner.executor import TurnComplete


@pytest.mark.parametrize("byte_cursor", [False, True])
def test_request_blobs_do_not_mirror_or_replay(tmp_path: Path, byte_cursor: bool) -> None:
    reminder = "<system-reminder>Contents of ~/CLAUDE.md: private context</system-reminder>"
    records = []
    for index, text in enumerate(("first message", "second message")):
        records.extend(
            [
                {
                    "type": "api-request-blob",
                    "hash": f"request-{index}",
                    "message": {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": reminder},
                            {"type": "text", "text": text},
                        ],
                    },
                },
                {
                    "type": "user",
                    "uuid": f"user-{index}",
                    "message": {"role": "user", "content": text},
                },
            ]
        )
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("".join(json.dumps(record) + "\n" for record in records))
    if byte_cursor:
        items = bridge.read_transcript_items_from_offset(
            transcript, 0, start_line=0, agent_name="claude"
        ).items
    else:
        _, _, items = bridge.read_transcript_items_since(transcript, 0, agent_name="claude")
    assert len(items) == 2
    history = [{"type": item.item_type, **item.data} for item in items]
    replay = main._claude_transcript_records_from_session_items(
        history,
        session_id="conversation",
        external_session_id="claude-session",
        cwd=tmp_path,
        bridge_dir=tmp_path,
    )
    assert [record["message"]["content"] for record in replay] == [
        "first message",
        "second message",
    ]
    assert "CLAUDE.md" not in json.dumps(replay)
    assert json.dumps(replay).count("second message") == 1
    # Filtering the mirror never rewrites Claude's native transcript.
    assert json.loads(transcript.read_text().splitlines()[0]) == records[0]


@pytest.mark.asyncio
async def test_two_turns_deliver_only_latest_text(monkeypatch, tmp_path: Path) -> None:
    payloads = []
    monkeypatch.setattr(
        bridge,
        "_wait_for_tmux_info",
        lambda *a, **k: {"socket_path": "test.sock", "tmux_target": "main"},
    )
    monkeypatch.setattr(bridge, "_restore_occupied_input", lambda *a, **k: None)
    monkeypatch.setattr(bridge, "_wait_for_claude_prompt_ready", lambda *a, **k: None)
    monkeypatch.setattr(bridge, "_paste_and_submit", lambda *a, text, **k: payloads.append(text))
    executor = claude_native_executor.ClaudeNativeExecutor(tmp_path)
    messages = []
    for text in ("first message", "second message"):
        messages.append({"role": "user", "content": [{"type": "input_text", "text": text}]})
        events = [
            event
            async for event in executor.run_turn(
                messages=messages, tools=[], system_prompt="Contents of ~/CLAUDE.md: context"
            )
        ]
        assert events == [TurnComplete(response=None)]
    assert payloads == ["first message", "second message"]
    assert "CLAUDE.md" not in payloads[1]
    assert payloads[1].count("second message") == 1
