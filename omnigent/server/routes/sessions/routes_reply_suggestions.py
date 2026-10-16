"""Opt-in suggestions. These routes never submit messages or resume agents."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import OrderedDict
from typing import Any

import httpx
from fastapi import APIRouter, Request

from omnigent.entities.conversation import Conversation, ConversationItem, MessageData
from omnigent.harnesses.codex_native.side_chat import is_side_chat_child
from omnigent.reply_suggestions import (
    ReplySuggestionRequest,
    ReplySuggestionResult,
    recent_context,
)
from omnigent.runner.routing import RunnerRouter
from omnigent.runtime import pending_elicitations
from omnigent.server.auth import LEVEL_EDIT, AuthProvider
from omnigent.server.routes._auth_helpers import require_access_and_level, require_user
from omnigent.server.routes._sessions.common import _session_status_cache
from omnigent.stores import ConversationStore
from omnigent.stores.permission_store import PermissionStore


def pending_async_question(items: list[ConversationItem], answered: set[str]) -> bool:
    """Async questions resolve through correlated user messages, not elicitations."""
    for item in items:
        if not isinstance(item.data, MessageData):
            continue
        reply = getattr(item.data, "async_question_reply", None)
        source = (
            reply.get("source_item_id")
            if isinstance(reply, dict)
            else getattr(reply, "source_item_id", None)
        )
        if isinstance(source, str):
            answered.add(source)
        if getattr(item.data, "async_user_input", None) is not None and item.id not in answered:
            return True
    return False


def register_reply_suggestion_routes(
    router: APIRouter,
    *,
    conversation_store: ConversationStore,
    runner_router: RunnerRouter | None,
    auth_provider: AuthProvider | None,
    permission_store: PermissionStore | None,
) -> None:
    # ponytail: one replica owns runner routing. Use a shared ledger if routing becomes multi-owner.
    jobs: OrderedDict[str, tuple[asyncio.Task[ReplySuggestionResult], str]] = OrderedDict()
    requests: dict[tuple[str | None, str, str], tuple[str, str]] = {}
    cancelled: OrderedDict[tuple[str | None, str, str], None] = OrderedDict()

    async def snapshot(session_id: str, response_id: str) -> tuple[Conversation, str] | None:
        conv = await asyncio.to_thread(conversation_store.get_conversation, session_id)
        if (
            conv is None
            or is_side_chat_child(conv.labels)
            or conv.archived
            or conv.labels.get("omnigent.closed") == "true"
            or _session_status_cache.get(session_id, conv.live_status) not in (None, "idle")
            or pending_elicitations.count_for(session_id)
        ):
            return None
        page = await asyncio.to_thread(
            conversation_store.list_items, session_id, 8, None, None, "desc", "message"
        )
        items = [
            (item, item.data)
            for item in page.data
            if isinstance(item.data, MessageData) and not item.data.is_meta
        ]
        if not items:
            return None
        answered: set[str] = set()
        if pending_async_question(page.data, answered):
            return None
        # On question-aware servers, inspect older metadata without sending it to the model.
        older = page
        while "async_user_input" in MessageData.model_fields and older.has_more:
            older = await asyncio.to_thread(
                conversation_store.list_items,
                session_id,
                200,
                older.last_id,
                None,
                "desc",
                "message",
            )
            if pending_async_question(older.data, answered):
                return None
        last, last_data = items[0]
        if (
            last.response_id != response_id
            or last.status != "completed"
            or last_data.role != "assistant"
            or last_data.interrupted
        ):
            return None
        messages = [
            (
                data.role,
                "\n".join(
                    block["text"]
                    for block in data.content
                    if block.get("type") in ("input_text", "output_text", "text")
                    and isinstance(block.get("text"), str)
                ),
            )
            for item, data in reversed(items[:4])
        ]
        return conv, recent_context(messages)

    def usage_key(response_id: str) -> str:
        return "omnigent.reply_usage." + hashlib.sha256(response_id.encode()).hexdigest()

    async def run(
        session_id: str, body: ReplySuggestionRequest, conv: Conversation, prompt: str
    ) -> ReplySuggestionResult:
        routed = (
            runner_router.client_for_existing_conversation(session_id) if runner_router else None
        )
        if routed is None:
            return ReplySuggestionResult(status="unsupported")
        try:
            response = await routed.client.post(
                f"/v1/sessions/{session_id}/next-reply",
                json={
                    **body.model_dump(),
                    "prompt": prompt,
                    "agent_id": conv.agent_id,
                    "harness_override": conv.harness_override,
                },
                timeout=20.0,
            )
            if response.status_code in (404, 501):
                return ReplySuggestionResult(status="unsupported")
            response.raise_for_status()
            result = ReplySuggestionResult.model_validate(response.json())
            if result.usage:
                # Keep an additive per-turn ledger separate from native cumulative SET totals.
                # ponytail: labels suffice for short sessions; move to a usage table at large scale.
                await asyncio.to_thread(
                    conversation_store.set_labels,
                    session_id,
                    {
                        usage_key(body.source_response_id): json.dumps(
                            {"model": result.model, "usage": result.usage}, separators=(",", ":")
                        )
                    },
                )
            current = await snapshot(session_id, body.source_response_id)
            if (
                current is None
                or current[1] != prompt
                or current[0].model_override != conv.model_override
            ):
                return result.model_copy(update={"status": "stale", "text": None})
            return result
        except (httpx.HTTPError, ValueError):
            return ReplySuggestionResult(status="unavailable")

    @router.post("/sessions/{session_id}/next-reply")
    async def generate(
        request: Request, session_id: str, body: ReplySuggestionRequest
    ) -> ReplySuggestionResult:
        user = require_user(request, auth_provider)
        await require_access_and_level(
            user, session_id, LEVEL_EDIT, permission_store, conversation_store
        )
        state = await snapshot(session_id, body.source_response_id)
        if state is None:
            return ReplySuggestionResult(status="stale")
        conv, prompt = state
        identity = (user, session_id, body.request_id)
        if identity in cancelled or await request.is_disconnected():
            return ReplySuggestionResult(status="unavailable")
        key = hashlib.sha256(
            json.dumps(
                [
                    session_id,
                    body.source_response_id,
                    conv.agent_id,
                    conv.model_override,
                    conv.harness_override,
                    conv.runner_id,
                    prompt,
                ]
            ).encode()
        ).hexdigest()
        if key not in jobs:
            # Do not regenerate a billed result after eviction or server restart.
            if usage_key(body.source_response_id) in conv.labels:
                return ReplySuggestionResult(status="none")
            # Never evict a pending job or start unbounded background work.
            while len(jobs) >= 128:
                finished = next((k for k, job in jobs.items() if job[0].done()), None)
                if finished is None:
                    return ReplySuggestionResult(status="unavailable")
                jobs.pop(finished)
            jobs[key] = (asyncio.create_task(run(session_id, body, conv, prompt)), body.request_id)
        requests[(user, session_id, body.request_id)] = (key, jobs[key][1])
        # The owner keeps draining/accounting even when the browser disconnects.
        try:
            result = await asyncio.shield(jobs[key][0])
            await require_access_and_level(
                user, session_id, LEVEL_EDIT, permission_store, conversation_store
            )
            return result
        finally:
            requests.pop((user, session_id, body.request_id), None)

    @router.delete("/sessions/{session_id}/next-reply/{request_id}")
    async def cancel(request: Request, session_id: str, request_id: str) -> dict[str, bool]:
        user = require_user(request, auth_provider)
        await require_access_and_level(
            user, session_id, LEVEL_EDIT, permission_store, conversation_store
        )
        entry = requests.pop((user, session_id, request_id), None)
        cancelled[(user, session_id, request_id)] = None
        if len(cancelled) > 256:
            cancelled.popitem(last=False)
        if entry is None or runner_router is None:
            return {"cancelled": False}
        routed = runner_router.client_for_existing_conversation(session_id)
        if routed is None:
            return {"cancelled": False}
        try:
            await routed.client.delete(
                f"/v1/sessions/{session_id}/next-reply/{entry[1]}", timeout=3.0
            )
        except httpx.HTTPError:
            return {"cancelled": False}
        return {"cancelled": True}

    @router.get("/sessions/{session_id}/next-reply/usage")
    async def usage(request: Request, session_id: str) -> dict[str, Any]:
        user = require_user(request, auth_provider)
        access = await require_access_and_level(
            user, session_id, LEVEL_EDIT, permission_store, conversation_store
        )
        conv = access.conversation or await asyncio.to_thread(
            conversation_store.get_conversation, session_id
        )
        totals: dict[str, int | float] = {}
        by_model: dict[str, dict[str, int | float]] = {}
        if conv is not None:
            for name, value in conv.labels.items():
                if not name.startswith("omnigent.reply_usage."):
                    continue
                try:
                    record = json.loads(value)
                    bucket = by_model.setdefault(record["model"], {})
                    for field, count in record["usage"].items():
                        if isinstance(count, (int, float)) and count >= 0:
                            totals[field] = totals.get(field, 0) + count
                            bucket[field] = bucket.get(field, 0) + count
                except (ValueError, KeyError, TypeError):
                    continue
        return {"usage": totals, "by_model": by_model}
