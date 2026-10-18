"""Reconcile metadata only through exact, owner-scoped native identities."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import TypeAdapter, ValidationError

from omnigent.entities.conversation import Conversation
from omnigent.native_observations import NativeId
from omnigent.stores import ConversationStore

MAX_MANAGED_SESSIONS = 10_000
_NATIVE_ID = TypeAdapter(NativeId)
_HARNESSES = {"codex-native": "codex", "claude-native": "claude", "acp:cline": "cline"}


def managed_inventory(
    store: ConversationStore,
    user: str,
    owned_hosts: set[str],
    resolve_harness: Callable[[Conversation], str | None],
) -> list[dict[str, Any]]:
    """Use the existing ownership filter; never fetch messages or import history."""
    conversations = []
    after = None
    seen = set()
    while True:
        page = store.list_conversations(
            limit=1000,
            after=after,
            kind=None,
            owned_by=user,
            include_archived=True,
            order="asc",
        )
        conversations.extend(page.data)
        if len(conversations) > MAX_MANAGED_SESSIONS:
            raise ValueError("Managed observation inventory exceeds its bound")
        if not page.has_more:
            break
        if not page.last_id or page.last_id in seen:
            raise ValueError("Managed observation cursor did not advance")
        seen.add(page.last_id)
        after = page.last_id
    owned_ids = {c.id for c in conversations}
    result = []
    for conv in conversations:
        harness = _HARNESSES.get(resolve_harness(conv) or "")
        try:
            native_id = _NATIVE_ID.validate_python(conv.external_session_id)
        except ValidationError:
            native_id = None
        host_id = conv.host_id if conv.host_id in owned_hosts else None
        result.append(
            {
                "session_id": conv.id,
                "host_id": host_id,
                "harness": harness,
                "native_id": native_id,
                "parent_session_id": conv.parent_conversation_id
                if conv.parent_conversation_id in owned_ids
                else None,
                "root_session_id": conv.root_conversation_id
                if conv.root_conversation_id in owned_ids
                else None,
                "archived": conv.archived,
                "reported_state": conv.live_status
                if conv.live_status in {"idle", "running", "waiting", "failed"}
                else None,
                # Neither updated_at nor runner heartbeat timestamps a state transition.
                "state_observed_at": None,
                "runner_last_seen": conv.runner_last_seen,
            }
        )
    return result


def reconcile_observations(
    native_rows: list[dict[str, Any]],
    managed: list[dict[str, Any]],
) -> list[tuple[tuple[str, str, str], dict[str, Any]]]:
    """One row per verified composite key; ambiguous bindings never choose a winner."""
    rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in native_rows:
        key = (item["host_id"], item["harness"], item["native_id"])
        rows[key] = {
            **item,
            "managed": [],
            "identity_status": "UNMATCHED",
            "provenance": ["native_observation"],
        }
    for item in managed:
        linked = all(item[field] is not None for field in ("host_id", "harness", "native_id"))
        key = (
            (item["host_id"], item["harness"], item["native_id"])
            if linked
            else (item["host_id"] or "~unbound", "managed", item["session_id"])
        )
        if key not in rows:
            rows[key] = {
                "host_id": item["host_id"],
                "harness": item["harness"],
                "native_id": item["native_id"],
                "source": "omnigent_managed",
                "managed": [],
                "provenance": [],
                "state": "UNKNOWN",
                "effective_state": "UNKNOWN",
                "observed_at": None,
                "fresh": False,
                "identity_status": "MANAGED_LINK" if linked else "UNRESOLVED",
                "context_tokens": None,
                "context_window": None,
            }
        row = rows[key]
        row["managed"].append(item)
        if "omnigent_managed" not in row["provenance"]:
            row["provenance"].append("omnigent_managed")
        if len(row["managed"]) > 1:
            row["identity_status"] = "AMBIGUOUS"
            row["effective_state"] = "UNKNOWN"
        elif row["source"] == "native_observation":
            row["identity_status"] = "VERIFIED"
            row["source"] = "reconciled"
            row["launch_origin"] = "managed"
    return sorted(rows.items())
