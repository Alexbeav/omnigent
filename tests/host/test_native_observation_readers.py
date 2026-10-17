"""Passive files and SQLite reads preserve native evidence and existing sessions."""

import asyncio
import hashlib
import json
import socket
import sqlite3
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from omnigent.host.native_observations import NativeObservationReader, publish_native_observations


def write_lines(path, records, *, mode="w"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode, encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record) + "\n")


def codex_header(native_id="native-one", **extra):
    return {
        "type": "session_meta",
        "payload": {
            "id": native_id,
            "timestamp": time.time() - 20,
            "source": "vscode",
            "originator": "Codex Desktop",
            "base_instructions": "private-content-canary",
            **extra,
        },
    }


def event(kind, observed, **extra):
    return {"type": "event_msg", "timestamp": observed, "payload": {"type": kind, **extra}}


def reader(tmp_path, **roots):
    return NativeObservationReader(tmp_path / "cursor.json", {k: [p] for k, p in roots.items()})


def source(scanner, harness):
    return next(s for s in scanner.scan() if s.harness == harness)


def test_codex_cursor_resume_preserves_activity_and_usage_times_without_content(tmp_path):
    root = tmp_path / "codex"
    now = time.time()
    write_lines(
        root / "rollout.jsonl",
        [
            codex_header(),
            event("task_started", now - 10),
            event(
                "token_count",
                now - 2,
                info={
                    "last_token_usage": {"total_tokens": 1200},
                    "total_token_usage": {"total_tokens": 999999},
                    "model_context_window": 200000,
                },
            ),
        ],
    )
    scanner = reader(tmp_path, codex=root)
    initial = source(scanner, "codex")
    row = initial.observations[0]
    assert row.state == "ACTIVE" and row.surface == "desktop"
    assert row.observed_at == now - 10 and row.context_observed_at == now - 2
    assert row.context_tokens == 1200 and row.context_window == 200000
    state = scanner.state_path.read_text()
    assert "private-content-canary" not in state and "base_instructions" not in state
    resumed = reader(tmp_path, codex=root)
    replay = source(resumed, "codex")
    assert replay.epoch == initial.epoch and replay.sequence > initial.sequence
    assert replay.observations == initial.observations
    assert source(resumed, "codex").observations == initial.observations


def test_codex_desktop_work_receipt_is_activity_without_exporting_tool_output(tmp_path):
    root = tmp_path / "desktop"
    now_ms = int(time.time() * 1000) - 1000
    receipt = event(
        "item_completed",
        time.time(),
        thread_id="native-one",
        completed_at_ms=now_ms,
        item={
            "type": "CommandExecution",
            "command": "private-command-canary",
            "aggregated_output": "private-output-canary",
        },
    )
    write_lines(
        root / "rollout.jsonl",
        [
            codex_header(),
            receipt,
            receipt
            | {
                "payload": receipt["payload"]
                | {"thread_id": "different-thread", "completed_at_ms": now_ms + 100}
            },
        ],
    )
    scanner = reader(tmp_path, codex=root)
    snapshot = source(scanner, "codex")
    row = snapshot.observations[0]
    assert row.event == "activity" and row.state == "ACTIVE"
    assert row.observed_at == now_ms / 1000
    assert "private-command-canary" not in scanner.state_path.read_text()
    assert "private-output-canary" not in snapshot.model_dump_json()


def test_previously_available_root_loss_cannot_establish_absence(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    write_lines(first / "one.jsonl", [codex_header("one")])
    write_lines(second / "two.jsonl", [codex_header("two")])
    scanner = NativeObservationReader(tmp_path / "cursor.json", {"codex": [first, second]})
    assert source(scanner, "codex").complete
    (second / "two.jsonl").unlink()
    second.rmdir()
    resumed = NativeObservationReader(scanner.state_path, scanner.roots)
    snapshot = source(resumed, "codex")
    assert snapshot.status == "PARTIAL" and not snapshot.complete


@pytest.mark.parametrize(
    "event_name,state,reason",
    [
        ("turn_start", "ACTIVE", None),
        ("turn_end", "IDLE", None),
        ("waiting", "WAITING", "permission"),
        ("error", "ERROR", None),
        ("session_end", "UNKNOWN", None),
    ],
)
def test_existing_hook_metadata_supplies_lifecycle_without_content_or_execution(
    tmp_path,
    event_name,
    state,
    reason,
):
    root = tmp_path / "existing-spool"
    now = time.time() - 1
    row = {
        "v": 1,
        "tool": "claude",
        "host": socket.gethostname().lower(),
        "session": "native-one",
        "event": event_name,
        "reason": reason,
        "ts": now,
        "title": "private-title-canary",
        "cwd": "/private-cwd-canary",
        "ctxTokens": 9999,
    }
    write_lines(root / "native-one.jsonl", [row])
    scanner = NativeObservationReader(tmp_path / "cursor.json", {}, {"claude": [root]})
    snapshot = source(scanner, "claude")
    assert "waiting" in snapshot.capabilities
    observation = snapshot.observations[0]
    assert observation.state == state and observation.observed_at == now
    assert observation.present == (event_name != "session_end")
    assert observation.context_tokens is None
    serialized = scanner.state_path.read_text()
    assert "private-title-canary" not in serialized and "private-cwd-canary" not in serialized


def test_foreign_host_and_unrecognized_notification_cannot_become_waiting(tmp_path):
    root = tmp_path / "existing-spool"
    row = {
        "v": 1,
        "tool": "claude",
        "host": "different-host",
        "session": "one",
        "event": "waiting",
        "reason": "permission",
        "ts": time.time() - 1,
    }
    write_lines(root / "one.jsonl", [row])
    write_lines(
        root / "two.jsonl",
        [
            row
            | {
                "host": socket.gethostname().lower(),
                "session": "two",
                "reason": "unrecognized-notification",
            }
        ],
    )
    scanner = NativeObservationReader(tmp_path / "cursor.json", {}, {"claude": [root]})
    snapshot = source(scanner, "claude")
    assert not snapshot.observations and snapshot.status == "PARTIAL"


def test_partial_tail_is_not_consumed_until_native_line_completes(tmp_path):
    root = tmp_path / "codex"
    path = root / "rollout.jsonl"
    now = time.time()
    write_lines(path, [codex_header(), event("task_started", now - 10)])
    scanner = reader(tmp_path, codex=root)
    assert source(scanner, "codex").observations[0].state == "ACTIVE"
    final = json.dumps(event("task_complete", now - 1))
    with path.open("a") as stream:
        stream.write(final[:20])
    partial = source(scanner, "codex")
    assert partial.status == "PARTIAL" and not partial.complete
    assert partial.observations[0].state == "ACTIVE"
    with path.open("a") as stream:
        stream.write(final[20:] + "\n")
    done = source(scanner, "codex")
    assert done.status == "CURRENT" and done.observations[0].state == "IDLE"
    assert done.observations[0].observed_at == now - 1


def test_rotation_and_regrowth_reset_identity_without_pid_matching(tmp_path):
    root = tmp_path / "codex"
    path = root / "rollout.jsonl"
    write_lines(path, [codex_header(), event("task_started", time.time() - 5)])
    scanner = reader(tmp_path, codex=root)
    assert source(scanner, "codex").observations[0].native_id == "native-one"
    write_lines(
        path,
        [
            codex_header("different-native", parent_thread_id="native-parent"),
            event("task_complete", time.time() - 1, error="private-error-canary"),
        ],
    )
    changed = source(scanner, "codex")
    assert len(changed.observations) == 1
    assert changed.observations[0].native_id == "different-native"
    assert changed.observations[0].parent_native_id == "native-parent"
    assert changed.observations[0].state == "ERROR"
    assert "private-error-canary" not in scanner.state_path.read_text()
    path.unlink()
    absent = source(scanner, "codex")
    assert absent.complete and absent.observations == []


def test_claude_parent_subagent_and_completion_remain_separate(tmp_path):
    root = tmp_path / "claude"
    now = time.time()
    parent = {
        "type": "assistant",
        "sessionId": "parent-id",
        "timestamp": now - 2,
        "entrypoint": "cli",
        "message": {
            "stop_reason": "end_turn",
            "content": "private-claude-canary",
            "usage": {"input_tokens": 987},
        },
    }
    write_lines(root / "parent-id.jsonl", [parent])
    write_lines(
        root / "parent-id/subagents/agent-child-id.jsonl",
        [
            parent | {"timestamp": now - 1, "message": {"stop_reason": "tool_use"}},
        ],
    )
    scanner = reader(tmp_path, claude=root)
    result = source(scanner, "claude")
    rows = {r.native_id: r for r in result.observations}
    assert rows["parent-id"].state == "IDLE"
    assert rows["parent-id:agent:child-id"].state == "ACTIVE"
    assert rows["parent-id:agent:child-id"].parent_native_id == "parent-id"
    assert all(r.context_tokens is None for r in rows.values())
    assert "waiting" not in result.capabilities and "usage" not in result.capabilities
    assert "private-claude-canary" not in scanner.state_path.read_text()


def cline_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE sessions (session_id TEXT, parent_session_id TEXT, source TEXT, "
        "started_at TEXT, ended_at TEXT, updated_at TEXT, status TEXT, prompt TEXT)"
    )
    conn.execute(
        "INSERT INTO sessions VALUES ('cline-one',NULL,'cli',?,?,?,?,?)",
        ("2026-10-17T00:00:00Z", None, "2026-10-17T00:00:01Z", "running", "private-cline-canary"),
    )
    conn.commit()
    return conn


def test_cline_reads_live_wal_metadata_without_claiming_live_state_or_writing(tmp_path):
    path = tmp_path / "sessions.db"
    conn = cline_db(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("UPDATE sessions SET updated_at='2026-10-17T00:00:02Z'")
        conn.commit()
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        scanner = reader(tmp_path, cline=path)
        snapshot = source(scanner, "cline")
        assert snapshot.capabilities == ["discovery"]
        assert snapshot.observations[0].state == "UNKNOWN"
        assert snapshot.observations[0].native_id == "cline-one"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before
        assert "private-cline-canary" not in scanner.state_path.read_text()
        assert "private-cline-canary" not in snapshot.model_dump_json()
        conn.execute("DELETE FROM sessions")
        conn.commit()
        assert source(scanner, "cline").observations == []
    finally:
        conn.close()


def test_cline_editor_discovery_does_not_read_transcript_or_rebrand_poll_time(tmp_path):
    root = tmp_path / "editor"
    task = root / "1730000000000/task_metadata.json"
    task.parent.mkdir(parents=True)
    task.write_text("not json: private-editor-canary")
    scanner = reader(tmp_path, cline=root)
    snapshot = source(scanner, "cline")
    row = snapshot.observations[0]
    assert row.native_id == "1730000000000" and row.surface == "editor"
    assert row.observed_at is None and row.state == "UNKNOWN"
    assert "private-editor-canary" not in scanner.state_path.read_text()


def test_missing_malformed_and_budget_limited_sources_never_claim_complete(tmp_path, monkeypatch):
    root = tmp_path / "codex"
    scanner = reader(tmp_path, codex=root)
    assert source(scanner, "codex").status == "UNAVAILABLE"
    write_lines(root / "bad.jsonl", [{"prompt": "private-unknown-canary"}])
    bad = source(scanner, "codex")
    assert bad.status == "PARTIAL" and not bad.complete and not bad.observations
    monkeypatch.setattr("omnigent.host.native_observations.MAX_READ_BYTES", 1)
    assert source(scanner, "codex").status == "PARTIAL"


def test_corrupt_cursor_file_rebuilds_from_native_evidence_without_redating(tmp_path):
    root = tmp_path / "codex"
    now = time.time()
    write_lines(root / "rollout.jsonl", [codex_header(), event("task_complete", now - 10)])
    scanner = reader(tmp_path, codex=root)
    original = source(scanner, "codex")
    scanner.state_path.write_text("{broken")
    rebuilt = source(reader(tmp_path, codex=root), "codex")
    assert rebuilt.epoch != original.epoch
    assert rebuilt.observations == original.observations


@pytest.mark.asyncio
async def test_publisher_reconnect_reuses_held_scan_without_waiting_for_disk(
    tmp_path, monkeypatch
):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    scanner = reader(tmp_path)
    original_scan = scanner.scan
    calls = []

    def scan():
        calls.append(1)
        started.set()
        try:
            release.wait(3)
            return original_scan()
        finally:
            finished.set()

    ws = SimpleNamespace(send=AsyncMock())
    monkeypatch.setattr(scanner, "scan", scan)
    task = asyncio.create_task(publish_native_observations(scanner, ws))
    try:
        async with asyncio.timeout(2):
            while not started.is_set():
                await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 0.5)
        assert not finished.is_set()
        ws.send.assert_not_called()
        # Repeated reconnects must not add disk workers or race the cursor file.
        for _ in range(5):
            task = asyncio.create_task(publish_native_observations(scanner, ws))
            await asyncio.sleep(0.01)
            assert len(calls) == 1
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 0.5)
        task = asyncio.create_task(publish_native_observations(scanner, ws))
        release.set()
        async with asyncio.timeout(2):
            while not ws.send.called:
                await asyncio.sleep(0.01)
        assert finished.is_set()
        assert len(calls) == 1
        assert json.loads(scanner.state_path.read_text())["sequence"] == 1
    finally:
        release.set()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


def test_reader_construction_does_not_read_cursor_on_the_event_loop(tmp_path, monkeypatch):
    from pathlib import Path

    original_stat = Path.stat
    state_path = tmp_path / "cursor.json"

    def no_cursor_io(path, *args, **kwargs):
        assert path != state_path, "cursor I/O must run inside the pending scan"
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", no_cursor_io)
    scanner = NativeObservationReader(state_path, {})
    assert scanner._pending_scan is None and scanner.sequence == 0


def test_reader_clock_repair_quarantines_unchanged_future_cursor_and_accepts_new_events(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("omnigent.host.native_observations.time.time", lambda: 2000)
    root = tmp_path / "codex"
    path = root / "rollout.jsonl"
    usage = {"last_token_usage": {"total_tokens": 1200}, "model_context_window": 200000}
    write_lines(
        path, [codex_header(), event("task_started", 2000), event("token_count", 2000, info=usage)]
    )
    scanner = reader(tmp_path, codex=root)
    assert source(scanner, "codex").observations[0].state == "ACTIVE"
    monkeypatch.setattr("omnigent.host.native_observations.time.time", lambda: 1001)
    resumed = reader(tmp_path, codex=root)
    quarantined = source(resumed, "codex").observations[0]
    assert quarantined.state == "UNKNOWN" and quarantined.observed_at is None
    assert quarantined.context_tokens is None and quarantined.context_observed_at is None
    write_lines(
        path, [event("task_complete", 1001), event("token_count", 1001, info=usage)], mode="a"
    )
    corrected = source(resumed, "codex").observations[0]
    assert corrected.state == "IDLE" and corrected.observed_at == 1001
    assert corrected.context_tokens == 1200 and corrected.context_observed_at == 1001
    assert source(reader(tmp_path, codex=root), "codex").observations == [corrected]


def test_future_usage_event_cannot_poison_current_native_cursor(tmp_path, monkeypatch):
    monkeypatch.setattr("omnigent.host.native_observations.time.time", lambda: 1000)
    root = tmp_path / "codex"
    usage = {"last_token_usage": {"total_tokens": 1234}, "model_context_window": 200000}
    write_lines(
        root / "rollout.jsonl",
        [
            codex_header(),
            event("task_started", 999),
            event("token_count", 2000, info=usage),
            event("token_count", 1000, info=usage),
        ],
    )
    row = source(reader(tmp_path, codex=root), "codex").observations[0]
    assert row.observed_at == 999 and row.state == "ACTIVE"
    assert row.context_tokens == 1234 and row.context_observed_at == 1000
