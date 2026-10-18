"""Latest resource sample, scoped to the authenticated host/account generation."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from omnigent.db.account_authority import require_active_account
from omnigent.db.db_models import SqlHost, SqlHostResourceSource, current_workspace_id
from omnigent.db.utils import make_named_managed_session_maker, run_write_transaction
from omnigent.host_resource_observations import HostResourceSnapshot

if TYPE_CHECKING:
    from omnigent.stores.host_store import Host


@dataclass(frozen=True)
class StoredHostResources:
    snapshot: HostResourceSnapshot | None
    received_at: float


class HostResourceStore:
    def __init__(self, engine: Engine) -> None:
        self._session = make_named_managed_session_maker(
            engine, query_name_prefix="omnigent.host_resource_store"
        )
        self._write = make_named_managed_session_maker(
            engine, query_name_prefix="omnigent.host_resource_store", immediate=True
        )

    def record(
        self,
        host_id: str,
        owner: str,
        snapshot: HostResourceSnapshot,
        *,
        is_current: Callable[[], bool] | None = None,
    ) -> bool:
        received_at = time.time()

        def write(session: Session) -> bool:
            workspace = current_workspace_id()
            host = session.execute(
                select(SqlHost)
                .where(SqlHost.workspace_id == workspace, SqlHost.host_id == host_id)
                .with_for_update()
            ).scalar_one_or_none()
            if host is None or host.user_id != owner or host.deleted_at is not None:
                raise ValueError("Resource host ownership mismatch")
            require_active_account(session, owner, generation=host.account_generation)
            if is_current is not None and not is_current():
                return False
            row = session.get(SqlHostResourceSource, (workspace, host_id))
            if (
                row is not None
                and row.owner == owner
                and row.account_generation == host.account_generation
            ):
                try:
                    previous = HostResourceSnapshot.model_validate_json(row.payload)
                except ValueError:
                    previous = None
                if previous is not None and (
                    (previous.epoch == snapshot.epoch and snapshot.sequence <= previous.sequence)
                    or (
                        snapshot.scanned_at < previous.scanned_at
                        and not (
                            abs(previous.scanned_at - row.received_at) > 5
                            and abs(snapshot.scanned_at - received_at) <= 5
                        )
                    )
                ):
                    return False
            if row is None:
                row = SqlHostResourceSource(workspace_id=workspace, host_id=host_id)
                session.add(row)
            row.owner = owner
            row.account_generation = host.account_generation
            row.payload = snapshot.model_dump_json()
            row.received_at = received_at
            return True

        return run_write_transaction(self._write, "record_host_resource_sample", write)

    def read_sources(self, hosts: Sequence[Host]) -> dict[str, StoredHostResources]:
        allowed = {h.host_id: h for h in hosts}
        if not allowed:
            return {}
        result = {}
        with self._session("read_host_resource_sources") as session:
            rows = session.execute(
                select(SqlHostResourceSource).where(
                    SqlHostResourceSource.workspace_id == current_workspace_id(),
                    SqlHostResourceSource.host_id.in_(allowed),
                )
            ).scalars()
            for row in rows:
                host = allowed[row.host_id]
                if row.owner != host.user_id or row.account_generation != host.account_generation:
                    continue
                try:
                    snapshot = HostResourceSnapshot.model_validate_json(row.payload)
                except ValueError:
                    snapshot = None
                result[row.host_id] = StoredHostResources(snapshot, row.received_at)
        return result
