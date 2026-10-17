"""Bounded passive native readers. Never import, launch or control a session."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import socket
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from omnigent.install_ledger import atomic_write_json
from omnigent.native_observations import (
    MAX_OBSERVATIONS,
    NativeObservation,
    NativeObservationSnapshot,
    quarantine_future_facts,
)

MAX_ENTRIES = 20_000
MAX_READ_BYTES = 4 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024
TAIL_BYTES = 256 * 1024
SCAN_SECONDS = 2.0
POLL_SECONDS = 30
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def _id(value: Any) -> str | None:
    return value if isinstance(value, str) and _ID.fullmatch(value) else None


def _timestamp(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return None
            value = parsed.timestamp()
        except ValueError:
            return None
    if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
        return float(value)
    return None


def default_roots() -> dict[str, list[Path]]:
    home = Path.home()
    roots = {
        "codex": [Path(os.environ.get("CODEX_HOME", str(home / ".codex"))) / "sessions"],
        "claude": [Path(os.environ.get("CLAUDE_CONFIG_DIR", str(home / ".claude"))) / "projects"],
        "cline": [home / ".cline/data/db/sessions.db"],
    }
    # Explicit editor roots; arbitrary application data is never recursively searched.
    editor_bases = [home / ".config/Code", home / "Library/Application Support/Code"]
    if os.environ.get("APPDATA"):
        editor_bases.append(Path(os.environ["APPDATA"]) / "Code")
    roots["cline"] += [p / "User/globalStorage/saoudrizwan.claude-dev/tasks" for p in editor_bases]
    return _configured_roots("OMNIGENT_NATIVE_OBSERVATION_ROOTS", roots)


def _configured_roots(variable: str, roots: dict[str, list[Path]]) -> dict[str, list[Path]]:
    raw = os.environ.get(variable)
    if raw:
        configured = json.loads(raw)
        if not isinstance(configured, dict) or set(configured) - set(roots):
            raise ValueError("Invalid passive native roots")
        for harness, paths in configured.items():
            if (
                not isinstance(paths, list)
                or not paths
                or len(paths) > 16
                or any(not isinstance(p, str) or not Path(p).is_absolute() for p in paths)
            ):
                raise ValueError("Passive native roots must be absolute paths")
            roots[harness] = [Path(p) for p in paths]
    return roots


def _hook_record(cursor: dict[str, Any], record: dict[str, Any], harness: str) -> None:
    """Consume an explicitly configured metadata spool without executing its hook."""
    if record.get("v") != 1 or record.get("tool") != harness:
        return
    if record.get("host") != socket.gethostname().lower():
        return
    native_id = _id(record.get("session"))
    if native_id is None:
        return
    agent = _id(record.get("agent"))
    parent = None
    if agent:
        parent, native_id = native_id, _id(f"{native_id}:agent:{agent}")
        if native_id is None:
            return
    cursor["meta"] = {"native_id": native_id, "parent_native_id": parent, "surface": "unknown"}
    kind = record.get("event")
    if kind == "waiting" and record.get("reason") not in {
        "permission",
        "permission_prompt",
        "idle_prompt",
        "elicitation_dialog",
    }:
        return
    states = {
        "session_start": "UNKNOWN",
        "turn_start": "ACTIVE",
        "turn_end": "IDLE",
        "waiting": "WAITING",
        "error": "ERROR",
        "session_end": "UNKNOWN",
    }
    if kind not in states:
        return
    _accept(cursor, _timestamp(record.get("ts")), states[kind], kind)
    if kind == "session_end" and cursor.get("row", {}).get("event") == kind:
        cursor["row"]["present"] = False


def _accept(cursor: dict[str, Any], observed: float | None, state: str, event: str) -> None:
    if observed is None or observed > time.time() + 5:
        return
    row = cursor.get("row")
    if row is not None:
        row = quarantine_future_facts(
            NativeObservation.model_validate(row), time.time()
        ).model_dump()
        cursor["row"] = row
    if row is not None and (row.get("observed_at") or -1) > observed:
        return
    cursor["row"] = {
        **(row or {}),
        **cursor["meta"],
        "observed_at": observed,
        "state": state,
        "event": event,
    }


def _record(cursor: dict[str, Any], record: dict[str, Any], harness: str, path: Path) -> None:
    payload = record.get("payload")
    if harness == "codex":
        if not isinstance(payload, dict):
            return
        if record.get("type") == "session_meta":
            native_id = _id(payload.get("id"))
            if native_id is None:
                return
            source = payload.get("source")
            originator = payload.get("originator")
            surface = (
                "desktop"
                if originator == "Codex Desktop"
                else (
                    "editor"
                    if source == "vscode"
                    else "cli"
                    if source in ("cli", "exec")
                    else "unknown"
                )
            )
            cursor["meta"] = {
                "native_id": native_id,
                "surface": surface,
                "parent_native_id": _id(payload.get("parent_thread_id")),
            }
            _accept(cursor, _timestamp(payload.get("timestamp")), "UNKNOWN", "session_start")
        if "meta" not in cursor:
            return
        if (
            payload.get("thread_id") is not None
            and payload["thread_id"] != cursor["meta"]["native_id"]
        ):
            return
        observed = _timestamp(record.get("timestamp"))
        kind = payload.get("type")
        if record.get("type") == "event_msg":
            transitions = {
                "task_started": ("ACTIVE", "turn_start"),
                "task_complete": ("IDLE", "turn_end"),
                "turn_aborted": ("UNKNOWN", "turn_end"),
            }
            if kind in transitions:
                state, event = transitions[kind]
                if kind == "task_complete" and payload.get("error") is not None:
                    state, event = "ERROR", "error"
                _accept(cursor, observed, state, event)
            elif kind == "item_completed" and isinstance(payload.get("item"), dict):
                # Native Desktop emits typed work receipts; never inspect their output.
                if payload["item"].get("type") in {
                    "FileChange",
                    "CommandExecution",
                    "Reasoning",
                    "AgentMessage",
                }:
                    completed = payload.get("completed_at_ms")
                    evidence = completed / 1000 if type(completed) is int else observed
                    _accept(cursor, _timestamp(evidence), "ACTIVE", "activity")
            elif kind == "token_count" and isinstance(payload.get("info"), dict):
                info = payload["info"]
                usage = info.get("last_token_usage")
                count = usage.get("total_tokens") if isinstance(usage, dict) else None
                window = info.get("model_context_window")
                if (
                    type(count) is int
                    and 0 <= count < 2**63
                    and observed is not None
                    and observed <= time.time() + 5
                ):
                    row = cursor.get("row")
                    if row and observed >= (row.get("context_observed_at") or -1):
                        row["context_tokens"], row["context_observed_at"] = count, observed
                        row["context_window"] = (
                            window if type(window) is int and 0 < window < 2**63 else None
                        )
    elif harness == "claude":
        native_id = _id(record.get("sessionId"))
        if native_id is None:
            return
        parent = None
        if "subagents" in path.parts:
            agent_id = path.stem.removeprefix("agent-")
            if not _id(agent_id):
                return
            parent, native_id = native_id, _id(f"{native_id}:agent:{agent_id}")
            if native_id is None:
                return
        entrypoint = record.get("entrypoint")
        surface = {"cli": "cli", "vscode": "editor", "desktop": "desktop"}.get(
            entrypoint if isinstance(entrypoint, str) else "", "unknown"
        )
        cursor["meta"] = {"native_id": native_id, "parent_native_id": parent, "surface": surface}
        observed = _timestamp(record.get("timestamp"))
        message = record.get("message")
        if record.get("type") == "assistant" and isinstance(message, dict):
            ended = message.get("stop_reason") == "end_turn"
            _accept(
                cursor, observed, "IDLE" if ended else "ACTIVE", "turn_end" if ended else "unknown"
            )
        elif "row" not in cursor:
            _accept(cursor, observed, "UNKNOWN", "unknown")


class NativeObservationReader:
    """Retain only whitelisted facts, file offsets and fingerprints between polls."""

    def __init__(
        self,
        state_path: Path,
        roots: dict[str, list[Path]] | None = None,
        event_roots: dict[str, list[Path]] | None = None,
    ) -> None:
        self.state_path = state_path
        self.roots = roots if roots is not None else default_roots()
        self.event_roots = (
            event_roots
            if event_roots is not None
            else _configured_roots(
                "OMNIGENT_NATIVE_EVENT_ROOTS",
                {"codex": [], "claude": [], "cline": []},
            )
        )
        self.epoch = uuid.uuid4().hex
        self.sequence = 0
        self.files: dict[str, dict[str, Any]] = {}
        self.available_roots: set[str] = set()
        self._pending_scan: asyncio.Task[list[NativeObservationSnapshot]] | None = None
        self._restore_pending = True

    def _restore(self) -> None:
        """Cursor reads belong to the same serialized disk worker as writes."""
        try:
            if self.state_path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("Oversized passive cursor state")
            stored = json.loads(self.state_path.read_text(encoding="utf-8"))
            if stored.get("version") != 1 or not re.fullmatch(r"[0-9a-f]{32}", stored["epoch"]):
                raise ValueError("Unsupported passive cursor state")
            if type(stored["sequence"]) is not int or not 0 <= stored["sequence"] < 2**63 - 1:
                raise ValueError("Invalid passive sequence")
            for key, cursor in stored["files"].items():
                if (
                    not re.fullmatch(r"[0-9a-f]{64}", key)
                    or len(self.files) >= MAX_OBSERVATIONS * 3
                ):
                    raise ValueError("Invalid passive file inventory")
                if type(cursor["offset"]) is not int or cursor["offset"] < 0:
                    raise ValueError("Invalid passive file offset")
                NativeObservation.model_validate(cursor["row"])
                self.files[key] = cursor
            self.epoch, self.sequence = stored["epoch"], stored["sequence"]
            self.available_roots = {
                key
                for key in stored.get("available_roots", [])
                if isinstance(key, str) and re.fullmatch(r"[0-9a-f]{64}", key)
            }
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            self.files = {}

    def _jsonl(
        self,
        path: Path,
        harness: str,
        remaining: int,
        *,
        events: bool = False,
    ) -> tuple[NativeObservation | None, int, bool]:
        key = hashlib.sha256((harness + str(events) + str(path.resolve())).encode()).hexdigest()
        consume = _hook_record if events else lambda c, r, h: _record(c, r, h, path)
        stat = path.stat()
        fingerprint = [stat.st_dev, stat.st_ino]
        old = self.files.get(key, {})
        if old.get("row"):
            old["row"] = quarantine_future_facts(
                NativeObservation.model_validate(old["row"]), time.time()
            ).model_dump()
        if (
            old.get("fingerprint") == fingerprint
            and old.get("offset") == stat.st_size
            and old.get("mtime_ns") == stat.st_mtime_ns
        ):
            return NativeObservation.model_validate(old["row"]), 0, False
        consumed = 0
        partial = False
        if remaining < MAX_LINE_BYTES:
            row = old.get("row")
            return NativeObservation.model_validate(row) if row else None, 0, True
        with path.open("rb") as stream:
            first = stream.readline(MAX_LINE_BYTES + 1)
            consumed += len(first)
            if len(first) > MAX_LINE_BYTES:
                return None, consumed, True
            head_hash = hashlib.sha256(first).hexdigest()
            cursor: dict[str, Any] = (
                dict(old)
                if old.get("fingerprint") == fingerprint
                and old.get("head_hash") == head_hash
                and stat.st_size >= old.get("offset", 0)
                else {}
            )
            cursor["fingerprint"], cursor["head_hash"] = fingerprint, head_hash
            offset = cursor.get("offset", 0)
            if offset == 0:
                try:
                    record = json.loads(first.decode("utf-8-sig"))
                    if isinstance(record, dict):
                        consume(cursor, record, harness)
                except (ValueError, UnicodeError):
                    partial = True
                offset = stream.tell()
                if stat.st_size - offset > TAIL_BYTES:
                    stream.seek(stat.st_size - TAIL_BYTES)
                    skipped = stream.readline(MAX_LINE_BYTES + 1)
                    consumed += len(skipped)
                    offset = stream.tell()
            stream.seek(offset)
            while (
                consumed < min(remaining, MAX_LINE_BYTES + TAIL_BYTES)
                and stream.tell() < stat.st_size
            ):
                before = stream.tell()
                line = stream.readline(min(MAX_LINE_BYTES + 1, remaining - consumed + 1))
                consumed += len(line)
                if not line.endswith(b"\n") or len(line) > MAX_LINE_BYTES:
                    stream.seek(before)
                    partial = True
                    break
                try:
                    record = json.loads(line.decode("utf-8"))
                    if isinstance(record, dict):
                        consume(cursor, record, harness)
                except (ValueError, UnicodeError):
                    partial = True
                offset = stream.tell()
            partial |= stream.tell() < stat.st_size
        cursor["offset"] = offset
        cursor["mtime_ns"] = stat.st_mtime_ns
        row = NativeObservation.model_validate(cursor["row"]) if cursor.get("row") else None
        if row is not None:
            cursor["row"] = row.model_dump()
            self.files[key] = cursor
        return row, consumed, partial

    def _cline(self, path: Path) -> tuple[list[NativeObservation], bool]:
        rows = []
        deadline = time.monotonic() + SCAN_SECONDS
        with closing(
            sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.05)
        ) as conn:
            conn.execute("PRAGMA query_only=ON")
            conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            # Deliberately exclude prompt, cwd, provider, transcript and metadata_json.
            values = conn.execute(
                "SELECT session_id, parent_session_id, source, started_at, ended_at, updated_at "
                "FROM sessions ORDER BY updated_at DESC LIMIT ?",
                (MAX_OBSERVATIONS + 1,),
            ).fetchall()
        for native_id, parent, source, started, ended, updated in values[:MAX_OBSERVATIONS]:
            if _id(native_id) is None:
                continue
            rows.append(
                NativeObservation(
                    native_id=native_id,
                    parent_native_id=_id(parent),
                    surface="cli" if source == "cli" else "unknown",
                    state="UNKNOWN",
                    observed_at=_timestamp(ended or updated or started),
                    event="session_end" if ended else "unknown",
                )
            )
        return rows, len(values) > MAX_OBSERVATIONS

    def scan(self) -> list[NativeObservationSnapshot]:
        if self._restore_pending:
            self._restore()
            self._restore_pending = False
        snapshots = []
        self.sequence += 1
        for harness in ("codex", "claude", "cline"):
            found: dict[str, NativeObservation] = {}
            partial, available = False, False
            entries, read_bytes = 0, 0
            deadline = time.monotonic() + SCAN_SECONDS
            event_available = False
            configured = [(p, True) for p in self.event_roots.get(harness, [])]
            configured += [(p, False) for p in self.roots.get(harness, [])]
            for root, events in configured:
                root_key = hashlib.sha256((harness + str(root.resolve())).encode()).hexdigest()
                if not root.exists():
                    partial |= root_key in self.available_roots or events
                    continue
                available = True
                event_available |= events
                self.available_roots.add(root_key)
                try:
                    if root.is_file():
                        if harness != "cline" or events:
                            partial = True
                            continue
                        rows, limited = self._cline(root)
                        partial |= limited
                        for row in rows:
                            found[row.native_id] = row
                        continue

                    def walk_error(error):
                        raise error

                    candidates = []
                    for directory, folders, names in os.walk(
                        root, followlinks=False, onerror=walk_error
                    ):
                        folders[:] = [f for f in folders if not (Path(directory) / f).is_symlink()]
                        for name in names:
                            entries += 1
                            if entries > MAX_ENTRIES or time.monotonic() > deadline:
                                partial = True
                                break
                            path = Path(directory) / name
                            if not path.is_symlink() and (
                                name == "task_metadata.json"
                                if harness == "cline" and not events
                                else name.endswith(".jsonl")
                            ):
                                candidates.append((path.stat().st_mtime_ns, path))
                        if (
                            entries > MAX_ENTRIES
                            or time.monotonic() > deadline
                            or len(found) >= MAX_OBSERVATIONS
                        ):
                            break
                    # Discover current sessions before spending a bounded read budget on archives.
                    for _, path in sorted(candidates, reverse=True):
                        if time.monotonic() > deadline:
                            partial = True
                            break
                        if harness == "cline" and not events:
                            if not _id(path.parent.name):
                                partial = True
                                continue
                            row = NativeObservation(
                                native_id=path.parent.name,
                                surface="editor",
                                state="UNKNOWN",
                                event="unknown",
                            )
                        else:
                            row, consumed, limited = self._jsonl(
                                path,
                                harness,
                                MAX_READ_BYTES - read_bytes,
                                events=events,
                            )
                            read_bytes += consumed
                            partial |= limited
                            if row is None:
                                partial = True
                                continue
                        existing = found.get(row.native_id)
                        if existing is None or (row.observed_at or -1) > (
                            existing.observed_at or -1
                        ):
                            found[row.native_id] = row
                        if len(found) >= MAX_OBSERVATIONS:
                            partial = True
                            break
                except (OSError, ValueError, sqlite3.Error):
                    partial = True
            capabilities = {
                "codex": ["discovery", "lifecycle", "usage"],
                "claude": ["discovery", "lifecycle"],
                "cline": ["discovery"],
            }[harness]
            if event_available:
                capabilities = ["discovery", "lifecycle", "waiting"]
                if harness == "codex":
                    capabilities.append("usage")
            status = "UNAVAILABLE" if not available else "PARTIAL" if partial else "CURRENT"
            snapshots.append(
                NativeObservationSnapshot.model_validate(
                    {
                        "harness": harness,
                        "epoch": self.epoch,
                        "sequence": self.sequence,
                        "scanned_at": time.time(),
                        "status": status,
                        "complete": status == "CURRENT",
                        "capabilities": capabilities,
                        "observations": list(found.values())[:MAX_OBSERVATIONS],
                    }
                )
            )
        # Cursor files contain no raw records. Bound accumulated file identities too.
        self.files = dict(list(self.files.items())[-MAX_OBSERVATIONS * 3 :])
        atomic_write_json(
            self.state_path,
            {
                "version": 1,
                "epoch": self.epoch,
                "sequence": self.sequence,
                "files": self.files,
                "available_roots": sorted(self.available_roots),
            },
        )
        return snapshots


async def publish_native_observations(reader: NativeObservationReader, ws: Any) -> None:
    """A separate task keeps passive disk reads away from tunnel keepalives."""
    from omnigent.host.frames import HostNativeObservationsFrame, encode_host_frame

    while True:
        if reader._pending_scan is None:
            reader._pending_scan = asyncio.create_task(asyncio.to_thread(reader.scan))
            # Observe an eventual I/O failure even if no connection returns to
            # consume the result. Awaiting the retained task still reports it.
            reader._pending_scan.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )
        worker = reader._pending_scan
        try:
            snapshots = await asyncio.shield(worker)
        finally:
            # The cached reader owns one cursor writer across reconnects. Cancelling
            # a connection never waits for disk I/O or starts a replacement scan.
            if worker.done():
                reader._pending_scan = None
        for snapshot in snapshots:
            async with asyncio.timeout(5):
                await ws.send(encode_host_frame(HostNativeObservationsFrame(snapshot)))
        await asyncio.sleep(POLL_SECONDS)
