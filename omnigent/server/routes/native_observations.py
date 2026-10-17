"""Owner-scoped, metadata-only read projection for passive native observations."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query, Request, Response

from omnigent.host_resource_observations import RESOURCE_TTL_S
from omnigent.native_observation_identity import managed_inventory, reconcile_observations
from omnigent.native_observations import MAX_CLOCK_LEAD_S, NATIVE_HARNESSES, OBSERVATION_TTL_S
from omnigent.server.auth import RESERVED_USER_LOCAL, AuthProvider
from omnigent.server.routes._auth_helpers import require_user
from omnigent.stores.host_store import HostStore, host_is_live

if TYPE_CHECKING:
    from omnigent.runtime.agent_cache import AgentCache
    from omnigent.stores import ConversationStore
    from omnigent.stores.agent_store import AgentStore


def _cursor(value: str | None) -> tuple[str, str, str] | None:
    if value is None:
        return None
    try:
        if len(value) > 1024:
            raise ValueError
        decoded = json.loads(
            base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
        )
        if (
            not isinstance(decoded, list)
            or len(decoded) != 3
            or any(not isinstance(item, str) or len(item) > 128 for item in decoded)
        ):
            raise ValueError
        return decoded[0], decoded[1], decoded[2]
    except (ValueError, UnicodeError, TypeError):
        raise HTTPException(400, "Invalid observation cursor") from None


def create_native_observations_router(
    host_store: HostStore,
    *,
    auth_provider: AuthProvider | None = None,
    conversation_store: ConversationStore | None = None,
    agent_store: AgentStore | None = None,
    agent_cache: AgentCache | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/observations")
    async def observations(
        request: Request,
        response: Response,
        limit: int = Query(default=100, ge=1, le=1000),
        after: str | None = Query(default=None, max_length=1024),
    ) -> dict[str, Any]:
        resolved_user = require_user(request, auth_provider)
        user = resolved_user if resolved_user is not None else RESERVED_USER_LOCAL
        start = _cursor(after)
        hosts = await asyncio.to_thread(host_store.list_hosts, user)
        stored = await asyncio.to_thread(host_store.observations.read_sources, hosts)
        managed = []
        if conversation_store is not None:
            from omnigent.server.routes._sessions.helpers import _resolve_harness_impl

            def resolve(conv):
                return _resolve_harness_impl(
                    conv, agent_store=agent_store, agent_cache=agent_cache
                )

            try:
                managed = await asyncio.to_thread(
                    managed_inventory,
                    conversation_store,
                    user,
                    {host.host_id for host in hosts},
                    resolve,
                )
            except ValueError:
                raise HTTPException(503, "Managed observation inventory unavailable") from None
        now = time.time()
        sources, rows = [], []
        for host in hosts:
            online = host_is_live(host, now=int(now))
            for harness in NATIVE_HARNESSES:
                entry = stored.get((host.host_id, harness))
                snapshot = entry.snapshot if entry else None
                status = "NOT_REPORTED"
                if entry:
                    status = snapshot.status if snapshot else "UNAVAILABLE"
                    if not online:
                        status = "UNAVAILABLE"
                    elif now - entry.received_at > OBSERVATION_TTL_S:
                        status = "STALE"
                    elif entry.received_at - now > MAX_CLOCK_LEAD_S or (
                        snapshot
                        and abs(snapshot.scanned_at - entry.received_at) > MAX_CLOCK_LEAD_S
                    ):
                        status = "CLOCK_SKEW"
                source = {
                    "host_id": host.host_id,
                    "harness": harness,
                    "host_online": online,
                    "status": status,
                    "reported_status": snapshot.status if snapshot else None,
                    "received_at": entry.received_at if entry else None,
                    "scanned_at": snapshot.scanned_at if snapshot else None,
                    "epoch": snapshot.epoch if snapshot else None,
                    "sequence": snapshot.sequence if snapshot else None,
                    "complete": bool(snapshot and snapshot.complete and status == "CURRENT"),
                    "capabilities": snapshot.capabilities if snapshot else [],
                }
                sources.append(source)
                if snapshot is None:
                    continue
                for item in snapshot.observations:
                    fresh = (
                        status in {"CURRENT", "PARTIAL"}
                        and item.observed_at is not None
                        and -MAX_CLOCK_LEAD_S <= now - item.observed_at <= OBSERVATION_TTL_S
                    )
                    rows.append(
                        {
                            **item.model_dump(),
                            "host_id": host.host_id,
                            "harness": harness,
                            "source": "native_observation",
                            "source_status": status,
                            "fresh": fresh,
                            "context_fresh": status in {"CURRENT", "PARTIAL"}
                            and "usage" in snapshot.capabilities
                            and item.context_observed_at is not None
                            and -MAX_CLOCK_LEAD_S
                            <= now - item.context_observed_at
                            <= OBSERVATION_TTL_S,
                            "effective_state": item.state
                            if fresh
                            and item.present
                            and "lifecycle" in snapshot.capabilities
                            and (item.state != "WAITING" or "waiting" in snapshot.capabilities)
                            else "UNKNOWN",
                        },
                    )
        reconciled = reconcile_observations(rows, managed)
        snapshot_id = hashlib.sha256(
            json.dumps(
                {
                    "rows": reconciled,
                    "sources": sources,
                    "managed_complete": conversation_store is not None,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        rows = [r for r in reconciled if start is None or r[0] > start]
        selected = rows[:limit]
        has_more = len(rows) > limit
        next_cursor = (
            base64.urlsafe_b64encode(json.dumps(selected[-1][0]).encode()).decode()
            if has_more
            else None
        )
        response.headers["Cache-Control"] = "no-store"
        return {
            "version": 1,
            "snapshot_id": snapshot_id,
            "as_of": now,
            "data": [row[1] for row in selected],
            "sources": sources,
            "managed_complete": conversation_store is not None,
            "has_more": has_more,
            "next_cursor": next_cursor,
        }

    @router.get("/resources")
    async def resources(request: Request, response: Response) -> dict[str, Any]:
        resolved = require_user(request, auth_provider)
        user = resolved if resolved is not None else RESERVED_USER_LOCAL
        hosts = await asyncio.to_thread(host_store.list_hosts, user)
        if len(hosts) > 1000:
            raise HTTPException(503, "Resource inventory exceeds its bound")
        stored = await asyncio.to_thread(host_store.resources.read_sources, hosts)
        now = time.time()
        data = []
        for host in hosts:
            entry = stored.get(host.host_id)
            snapshot = entry.snapshot if entry else None
            status = "NOT_REPORTED"
            if entry:
                status = (
                    "UNAVAILABLE"
                    if snapshot is None or not host_is_live(host, int(now))
                    else snapshot.sample.status
                )
                if snapshot and (
                    abs(snapshot.scanned_at - entry.received_at) > MAX_CLOCK_LEAD_S
                    or entry.received_at > now + MAX_CLOCK_LEAD_S
                ):
                    status = "CLOCK_SKEW"
                elif now - entry.received_at > RESOURCE_TTL_S or (
                    snapshot and now - snapshot.scanned_at > RESOURCE_TTL_S
                ):
                    status = "STALE"
            data.append(
                {
                    "host_id": host.host_id,
                    "host_online": host_is_live(host, int(now)),
                    "status": status,
                    "received_at": entry.received_at if entry else None,
                    "snapshot": snapshot.model_dump() if snapshot else None,
                }
            )
        response.headers["Cache-Control"] = "no-store"
        return {"version": 1, "as_of": now, "data": data, "complete": True}

    return router
