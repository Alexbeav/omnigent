"""Passive metadata has an additive, reversible migration."""

from importlib import import_module

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.orm import Session

from omnigent.db.db_models import SqlNativeObservationSource
from omnigent.db.utils import _build_alembic_config


def test_native_observation_migration_round_trip_preserves_existing_tables(tmp_path):
    uri = f"sqlite:///{tmp_path / 'passive-migration.db'}"
    engine = sa.create_engine(uri)
    migration = import_module(
        "omnigent.db.migrations.versions.ae06bdc7f981_add_native_observation_sources"
    )
    scripts = ScriptDirectory.from_config(_build_alembic_config(uri))
    assert scripts.get_heads() == ["c28e71a4b905"]
    assert scripts.get_revision(migration.revision).down_revision == migration.down_revision
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE existing_sessions (id INTEGER PRIMARY KEY)"))
            connection.execute(sa.text("INSERT INTO existing_sessions VALUES (7)"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
        with Session(engine) as session:
            session.add(
                SqlNativeObservationSource(
                    workspace_id=0,
                    host_id="a" * 32,
                    harness="codex",
                    owner="alice",
                    payload='{"metadata":"qualified"}',
                    received_at=1000,
                )
            )
            session.commit()
            row = session.get(SqlNativeObservationSource, (0, "a" * 32, "codex"))
            assert row.payload == '{"metadata":"qualified"}'
            assert row.received_at == 1000
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade()
            assert connection.scalar(sa.text("SELECT id FROM existing_sessions")) == 7
        assert sa.inspect(engine).get_table_names() == ["existing_sessions"]
    finally:
        engine.dispose()


def test_resource_migration_roundtrip_preserves_existing_sessions(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'resources.db'}")
    migration = import_module(
        "omnigent.db.migrations.versions.c28e71a4b905_add_host_resource_sources"
    )
    from omnigent.db.db_models import SqlHostResourceSource

    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE existing_sessions (id INTEGER PRIMARY KEY)"))
            connection.execute(sa.text("INSERT INTO existing_sessions VALUES (7)"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
        with Session(engine) as session:
            session.add(
                SqlHostResourceSource(
                    workspace_id=0,
                    host_id="a" * 32,
                    owner="alice",
                    payload='{"sample":1}',
                    received_at=1000,
                )
            )
            session.commit()
            assert session.get(SqlHostResourceSource, (0, "a" * 32)).payload == '{"sample":1}'
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade()
            assert connection.scalar(sa.text("SELECT id FROM existing_sessions")) == 7
    finally:
        engine.dispose()
