"""Latest passive metadata per host and harness; no conversation writes."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from omnigent.db.account_authority import require_active_account
from omnigent.db.db_models import SqlHost, SqlNativeObservationSource, current_workspace_id
from omnigent.db.utils import make_named_managed_session_maker, run_write_transaction
from omnigent.native_observations import (
    MAX_CLOCK_LEAD_S,
    MAX_OBSERVATIONS,
    NativeObservationSnapshot,
    quarantine_future_facts,
)

if TYPE_CHECKING:
    from omnigent.stores.host_store import Host


@dataclass(frozen=True)
class StoredObservationSource:
    snapshot: NativeObservationSnapshot | None
    received_at: float


class NativeObservationStore:
    def __init__(self, engine: Engine) -> None:
        self._session = make_named_managed_session_maker(
            engine, query_name_prefix="omnigent.native_observation_store"
        )
        self._write = make_named_managed_session_maker(
            engine, query_name_prefix="omnigent.native_observation_store", immediate=True
        )

    def record(
        self,
        host_id: str,
        owner: str,
        snapshot: NativeObservationSnapshot,
        *,
        is_current: Callable[[], bool] | None = None,
    ) -> bool:
        """Record a validated fact from the authenticated current host tunnel."""
        received_at = time.time()

        def write(session: Session) -> bool:
            workspace = current_workspace_id()
            host = session.execute(
                select(SqlHost)
                .where(SqlHost.workspace_id == workspace, SqlHost.host_id == host_id)
                .with_for_update()
            ).scalar_one_or_none()
            if host is None or host.user_id != owner or host.deleted_at is not None:
                raise ValueError("Observation host ownership mismatch")
            require_active_account(session, owner, generation=host.account_generation)
            if is_current is not None and not is_current():
                return False
            row = session.get(SqlNativeObservationSource, (workspace, host_id, snapshot.harness))
            previous = None
            if (
                row is not None
                and row.owner == owner
                and row.account_generation == host.account_generation
            ):
                try:
                    previous = NativeObservationSnapshot.model_validate_json(
                        row.payload, context={"retained_facts": True}
                    )
                except ValueError:
                    previous = None
            if previous is not None:
                if previous.epoch == snapshot.epoch and snapshot.sequence <= previous.sequence:
                    return False
                if snapshot.scanned_at < previous.scanned_at and not (
                    row is not None
                    and previous.scanned_at > row.received_at + MAX_CLOCK_LEAD_S
                    and abs(snapshot.scanned_at - received_at) <= MAX_CLOCK_LEAD_S
                ):
                    return False
            observations = {item.native_id: item for item in snapshot.observations}
            if previous is not None:
                for item in previous.observations:
                    # A future clock must not poison either independently timed fact.
                    assert row is not None
                    item = quarantine_future_facts(item, min(row.received_at, received_at))
                    incoming = observations.get(item.native_id)
                    if incoming is None and not snapshot.complete:
                        observations[item.native_id] = item
                    elif incoming is not None:
                        updates = {}
                        if (incoming.observed_at or -1) < (item.observed_at or -1):
                            updates.update(
                                state=item.state,
                                event=item.event,
                                observed_at=item.observed_at,
                                present=item.present and incoming.present,
                            )
                        if (incoming.context_observed_at or -1) < (item.context_observed_at or -1):
                            updates.update(
                                context_tokens=item.context_tokens,
                                context_window=item.context_window,
                                context_observed_at=item.context_observed_at,
                            )
                        observations[item.native_id] = incoming.model_copy(update=updates)
            if len(observations) > MAX_OBSERVATIONS:
                raise ValueError("Retained observation inventory exceeds its bound")
            retained = NativeObservationSnapshot.model_validate(
                {**snapshot.model_dump(), "observations": list(observations.values())},
                context={"retained_facts": True},
            )
            if row is None:
                row = SqlNativeObservationSource(
                    workspace_id=workspace, host_id=host_id, harness=snapshot.harness
                )
                session.add(row)
            row.owner = owner
            row.account_generation = host.account_generation
            row.payload = retained.model_dump_json()
            row.received_at = received_at
            return True

        return run_write_transaction(self._write, "record_native_observation_source", write)

    def read_sources(
        self, hosts: Sequence[Host]
    ) -> dict[tuple[str, str], StoredObservationSource]:
        """Read only currently owned host/account generations in this workspace."""
        allowed = {host.host_id: host for host in hosts}
        if not allowed:
            return {}
        result = {}
        with self._session("read_native_observation_sources") as session:
            rows = session.execute(
                select(SqlNativeObservationSource).where(
                    SqlNativeObservationSource.workspace_id == current_workspace_id(),
                    SqlNativeObservationSource.host_id.in_(allowed),
                )
            ).scalars()
            for row in rows:
                host = allowed[row.host_id]
                if row.owner != host.user_id or row.account_generation != host.account_generation:
                    continue
                try:
                    snapshot = NativeObservationSnapshot.model_validate_json(
                        row.payload, context={"retained_facts": True}
                    )
                except ValueError:
                    snapshot = None
                result[(row.host_id, row.harness)] = StoredObservationSource(
                    snapshot=snapshot, received_at=row.received_at
                )
        return result
