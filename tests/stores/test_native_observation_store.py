"""Passive metadata cannot cross owners, workspaces or evidence generations."""

import uuid

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from omnigent.db.db_models import SqlHost, SqlNativeObservationSource, workspace_scope
from omnigent.db.utils import get_or_create_engine
from omnigent.native_observations import NativeObservationSnapshot
from omnigent.stores.host_store import HostStore


def inventory(
    sequence=1, *, epoch="a" * 32, scanned_at=1000, complete=True, rows=None, capabilities=None
):
    return NativeObservationSnapshot.model_validate(
        {
            "harness": "codex",
            "epoch": epoch,
            "sequence": sequence,
            "scanned_at": scanned_at,
            "status": "CURRENT" if complete else "PARTIAL",
            "complete": complete,
            "capabilities": capabilities
            if capabilities is not None
            else ["discovery", "lifecycle"],
            "observations": rows
            if rows is not None
            else [
                {"native_id": "one", "state": "ACTIVE", "event": "turn_start", "observed_at": 999}
            ],
        }
    )


def test_replayed_frame_cannot_refresh_receipt_or_roll_back_facts(db_uri, monkeypatch):
    hosts = HostStore(db_uri)
    host = hosts.upsert_on_connect(uuid.uuid4().hex, "reader", "alice")
    monkeypatch.setattr("omnigent.stores.native_observation_store.time.time", lambda: 1000)
    assert hosts.observations.record(host.host_id, "alice", inventory())
    monkeypatch.setattr("omnigent.stores.native_observation_store.time.time", lambda: 2000)
    assert not hosts.observations.record(host.host_id, "alice", inventory())
    assert not hosts.observations.record(
        host.host_id, "alice", inventory(0, epoch="b" * 32, scanned_at=900, rows=[])
    )
    loaded = hosts.observations.read_sources([host])[(host.host_id, "codex")]
    assert loaded.received_at == 1000
    assert loaded.snapshot.observations[0].observed_at == 999


@pytest.mark.parametrize("epoch", ["a" * 32, "b" * 32])
def test_native_clock_repair_quarantines_future_facts_without_relaxing_replay(
    db_uri, monkeypatch, epoch
):
    hosts = HostStore(db_uri)
    host = hosts.upsert_on_connect(uuid.uuid4().hex, "reader", "alice")
    monkeypatch.setattr("omnigent.stores.native_observation_store.time.time", lambda: 1000)
    future = {
        "native_id": "one",
        "state": "ACTIVE",
        "event": "turn_start",
        "observed_at": 2000,
        "context_tokens": 1234,
        "context_window": 200000,
        "context_observed_at": 2000,
    }
    initial = inventory(
        scanned_at=2000,
        rows=[
            future,
            future
            | {
                "native_id": "missing",
                "state": "UNKNOWN",
                "event": "session_end",
                "present": False,
            },
        ],
        capabilities=["discovery", "lifecycle", "usage"],
    )
    assert hosts.observations.record(host.host_id, "alice", initial)
    monkeypatch.setattr("omnigent.stores.native_observation_store.time.time", lambda: 1001)
    fixed = inventory(
        2,
        epoch=epoch,
        scanned_at=1001,
        complete=False,
        rows=[
            {
                "native_id": "one",
                "state": "IDLE",
                "event": "turn_end",
                "observed_at": 1001,
            }
        ],
    )
    assert hosts.observations.record(host.host_id, "alice", fixed)
    loaded = hosts.observations.read_sources([host])[(host.host_id, "codex")]
    assert loaded.received_at == 1001 and loaded.snapshot.scanned_at == 1001
    rows = {row.native_id: row for row in loaded.snapshot.observations}
    assert rows["one"].state == "IDLE" and rows["one"].observed_at == 1001
    assert rows["one"].context_tokens is None and rows["one"].context_observed_at is None
    assert rows["missing"].state == "UNKNOWN" and rows["missing"].observed_at is None
    assert rows["missing"].present
    assert rows["missing"].context_tokens is None and rows["missing"].context_observed_at is None
    assert not hosts.observations.record(host.host_id, "alice", fixed)
    assert not hosts.observations.record(
        host.host_id, "alice", inventory(3, epoch=epoch, scanned_at=999)
    )
    assert not hosts.observations.record(
        host.host_id, "alice", inventory(1, epoch="c" * 32, scanned_at=999)
    )


def test_native_store_rejects_replaced_connection_after_waiting_for_transaction(db_uri):
    hosts = HostStore(db_uri)
    host = hosts.upsert_on_connect(uuid.uuid4().hex, "reader", "alice")
    assert not hosts.observations.record(
        host.host_id, "alice", inventory(), is_current=lambda: False
    )
    assert hosts.observations.read_sources([host]) == {}


def test_partial_scan_retains_missing_rows_and_older_events_do_not_win(db_uri):
    hosts = HostStore(db_uri)
    host = hosts.upsert_on_connect(uuid.uuid4().hex, "reader", "alice")
    row = inventory().observations[0].model_dump()
    hosts.observations.record(
        host.host_id, "alice", inventory(rows=[row, row | {"native_id": "two"}])
    )
    older = row | {"state": "IDLE", "event": "turn_end", "observed_at": 900}
    hosts.observations.record(
        host.host_id, "alice", inventory(2, scanned_at=1010, complete=False, rows=[older])
    )
    loaded = hosts.observations.read_sources([host])[(host.host_id, "codex")].snapshot
    assert {r.native_id for r in loaded.observations} == {"one", "two"}
    assert all(r.state == "ACTIVE" and r.observed_at == 999 for r in loaded.observations)
    hosts.observations.record(host.host_id, "alice", inventory(3, scanned_at=1020, rows=[]))
    assert not hosts.observations.read_sources([host])[
        (host.host_id, "codex")
    ].snapshot.observations


def test_owner_reassignment_never_exposes_or_merges_previous_owner_data(db_uri):
    hosts = HostStore(db_uri)
    host = hosts.upsert_on_connect(uuid.uuid4().hex, "reader", "alice")
    hosts.observations.record(host.host_id, "alice", inventory())
    with Session(get_or_create_engine(db_uri)) as session:
        session.execute(
            update(SqlHost).where(SqlHost.host_id == host.host_id).values(user_id="bob")
        )
        session.commit()
    bob = hosts.get_host(host.host_id)
    assert hosts.observations.read_sources([bob]) == {}
    with pytest.raises(ValueError, match="ownership"):
        hosts.observations.record(host.host_id, "alice", inventory(2))
    assert hosts.observations.record(host.host_id, "bob", inventory(2, complete=False, rows=[]))
    assert (
        hosts.observations.read_sources([bob])[(host.host_id, "codex")].snapshot.observations == []
    )


def test_snapshot_is_workspace_scoped_and_account_generation_scoped(db_uri):
    hosts = HostStore(db_uri)
    host_id = uuid.uuid4().hex
    with workspace_scope(1):
        first = hosts.upsert_on_connect(host_id, "reader", "alice")
        hosts.observations.record(host_id, "alice", inventory())
        with Session(get_or_create_engine(db_uri)) as session:
            session.execute(
                update(SqlNativeObservationSource)
                .where(SqlNativeObservationSource.host_id == host_id)
                .values(account_generation="b" * 32)
            )
            session.commit()
        assert hosts.observations.read_sources([first]) == {}
    with workspace_scope(2):
        second = hosts.upsert_on_connect(host_id, "reader", "alice")
        assert hosts.observations.read_sources([second]) == {}


def test_corrupt_payload_is_unavailable_and_next_valid_frame_repairs_it(db_uri):
    hosts = HostStore(db_uri)
    host = hosts.upsert_on_connect(uuid.uuid4().hex, "reader", "alice")
    hosts.observations.record(host.host_id, "alice", inventory())
    with Session(get_or_create_engine(db_uri)) as session:
        session.execute(
            update(SqlNativeObservationSource)
            .where(SqlNativeObservationSource.host_id == host.host_id)
            .values(payload="{}")
        )
        session.commit()
    assert hosts.observations.read_sources([host])[(host.host_id, "codex")].snapshot is None
    assert hosts.observations.record(host.host_id, "alice", inventory(2))
    assert hosts.observations.read_sources([host])[(host.host_id, "codex")].snapshot is not None


def test_capability_loss_retains_qualified_history_without_advertising_support(db_uri):
    hosts = HostStore(db_uri)
    host = hosts.upsert_on_connect(uuid.uuid4().hex, "reader", "alice")
    hosts.observations.record(host.host_id, "alice", inventory())
    reduced = NativeObservationSnapshot.model_validate(
        inventory(2, scanned_at=1010, complete=False, rows=[]).model_dump()
        | {"capabilities": ["discovery"]}
    )
    assert hosts.observations.record(host.host_id, "alice", reduced)
    loaded = hosts.observations.read_sources([host])[(host.host_id, "codex")].snapshot
    assert loaded.capabilities == ["discovery"]
    assert loaded.observations[0].state == "ACTIVE"
    assert loaded.observations[0].observed_at == 999
    unavailable = NativeObservationSnapshot.model_validate(
        reduced.model_dump() | {"sequence": 3, "scanned_at": 1020, "status": "UNAVAILABLE"}
    )
    assert hosts.observations.record(host.host_id, "alice", unavailable)
    assert hosts.observations.read_sources([host])[(host.host_id, "codex")].snapshot.status == (
        "UNAVAILABLE"
    )


def test_usage_and_lifecycle_evidence_merge_independently(db_uri):
    hosts = HostStore(db_uri)
    host = hosts.upsert_on_connect(uuid.uuid4().hex, "reader", "alice")
    row = inventory().observations[0].model_dump()
    first = NativeObservationSnapshot.model_validate(
        inventory().model_dump()
        | {
            "capabilities": ["discovery", "lifecycle", "usage"],
            "observations": [row | {"context_tokens": 100, "context_observed_at": 995}],
        }
    )
    hosts.observations.record(host.host_id, "alice", first)
    second = NativeObservationSnapshot.model_validate(
        first.model_dump()
        | {
            "sequence": 2,
            "scanned_at": 1010,
            "observations": [
                row
                | {
                    "observed_at": 990,
                    "state": "IDLE",
                    "event": "turn_end",
                    "context_tokens": 200,
                    "context_observed_at": 1005,
                }
            ],
        }
    )
    hosts.observations.record(host.host_id, "alice", second)
    merged = hosts.observations.read_sources([host])[
        (host.host_id, "codex")
    ].snapshot.observations[0]
    assert merged.state == "ACTIVE" and merged.observed_at == 999
    assert merged.context_tokens == 200 and merged.context_observed_at == 1005
