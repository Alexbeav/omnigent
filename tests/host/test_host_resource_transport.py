"""Bounded hardware metadata cannot refresh old evidence or block the tunnel."""

import asyncio
import json
import threading
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.orm import Session

from omnigent.db.db_models import SqlHost, workspace_scope
from omnigent.db.utils import get_or_create_engine
from omnigent.host.frames import (
    HostResourceObservationsFrame,
    decode_host_frame,
    encode_host_frame,
)
from omnigent.host_resource_observations import HostResourceSnapshot
from omnigent.stores.host_store import HostStore


def resource_inventory(*, now=1000, sequence=1, environment="native"):
    stamp = datetime.fromtimestamp(now, UTC).isoformat()
    return HostResourceSnapshot.model_validate(
        {
            "epoch": "a" * 32,
            "sequence": sequence,
            "scanned_at": now,
            "environment": environment,
            "sample": {
                "schema_version": 1,
                "status": "CURRENT",
                "observed_at": stamp,
                "cpu_percent": 25,
                "cpu_observed_at": stamp,
                "cpu_interval_seconds": 0.25,
                "memory": {"total_bytes": 1000, "available_bytes": 400, "used_percent": 60},
                "memory_observed_at": stamp,
                "memory_definition": "100 * (physical total - OS available) / physical total",
                "gpu": {
                    "status": "UNSUPPORTED",
                    "reason": "GPU_ADAPTER_NOT_IMPLEMENTED",
                    "devices": [],
                },
            },
        }
    )


def test_resource_frame_roundtrip_and_content_rejection():
    frame = HostResourceObservationsFrame(resource_inventory())
    assert decode_host_frame(encode_host_frame(frame)) == frame
    for name in ("host_id", "owner", "prompt", "path", "processes"):
        body = frame.snapshot.model_dump()
        body["sample"][name] = "PRIVATE-CANARY"
        with pytest.raises(ValueError, match=r"^Invalid host resource metadata$"):
            decode_host_frame(json.dumps({"kind": "host.resource_observations", "snapshot": body}))


@pytest.mark.parametrize("change", ["nan", "memory", "timezone", "gpu", "bool", "future"])
def test_contradictory_resource_claims_are_rejected(change):
    body = resource_inventory().model_dump()
    if change == "nan":
        body["sample"]["cpu_percent"] = float("nan")
    if change == "memory":
        body["sample"]["memory"]["used_percent"] = 10
    if change == "timezone":
        body["sample"]["cpu_observed_at"] = "2026-10-17T00:00:00"
    if change == "gpu":
        body["sample"]["gpu"]["status"] = "CURRENT"
    if change == "bool":
        body["sequence"] = True
    if change == "future":
        body["sample"]["observed_at"] = "2030-01-01T00:00:00Z"
    with pytest.raises(ValidationError):
        HostResourceSnapshot.model_validate(body)


def test_resource_store_replay_owner_and_workspace_fences(db_uri, monkeypatch):
    store = HostStore(db_uri)
    host_id = uuid.uuid4().hex
    with workspace_scope(1):
        host = store.upsert_on_connect(host_id, "physical", "alice")
        monkeypatch.setattr("omnigent.stores.host_resource_store.time.time", lambda: 1000)
        assert store.resources.record(host_id, "alice", resource_inventory())
        monkeypatch.setattr("omnigent.stores.host_resource_store.time.time", lambda: 2000)
        assert not store.resources.record(host_id, "alice", resource_inventory())
        assert not store.resources.record(
            host_id, "alice", resource_inventory(now=999, sequence=2)
        )
        assert store.resources.read_sources([host])[host_id].received_at == 1000
        with Session(get_or_create_engine(db_uri)) as session:
            session.execute(
                update(SqlHost)
                .where(SqlHost.workspace_id == 1, SqlHost.host_id == host_id)
                .values(user_id="bob")
            )
            session.commit()
        bob = store.get_host(host_id)
        assert store.resources.read_sources([bob]) == {}
        with pytest.raises(ValueError, match="ownership"):
            store.resources.record(host_id, "alice", resource_inventory(sequence=2))
    with workspace_scope(2):
        second = store.upsert_on_connect(host_id, "other", "alice")
        assert store.resources.read_sources([second]) == {}


def test_repaired_clock_can_replace_a_skewed_resource_sample(db_uri, monkeypatch):
    store = HostStore(db_uri)
    host = store.upsert_on_connect(uuid.uuid4().hex, "physical", "alice")
    monkeypatch.setattr("omnigent.stores.host_resource_store.time.time", lambda: 1000)
    assert store.resources.record(host.host_id, "alice", resource_inventory(now=1010))
    monkeypatch.setattr("omnigent.stores.host_resource_store.time.time", lambda: 1001)
    assert store.resources.record(host.host_id, "alice", resource_inventory(now=1001, sequence=2))
    assert store.resources.read_sources([host])[host.host_id].snapshot.scanned_at == 1001


async def test_cancelled_sampling_keeps_one_worker_and_leaves_event_loop_running(monkeypatch):
    from omnigent.host import resource_publisher

    started, release = threading.Event(), threading.Event()
    calls = []

    def sample():
        calls.append(1)
        started.set()
        release.wait(3)
        return resource_inventory().sample.model_dump()

    monkeypatch.setattr(resource_publisher, "sample_host_resources", sample)
    publisher = resource_publisher.HostResourcePublisher()
    first = asyncio.create_task(publisher.sample())
    try:
        async with asyncio.timeout(1):
            while not started.is_set():
                await asyncio.sleep(0.001)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(publisher.sample())
        await asyncio.sleep(0.01)
        assert len(calls) == 1 and not second.done()
        release.set()
        measured = await second
        assert measured.sample.cpu_percent == 25 and publisher.sequence == 1
    finally:
        release.set()
