"""Exact native identity never guesses a host, parent harness or ACP client."""

import pytest

from omnigent.native_observation_identity import reconcile_observations


def managed(session_id="one", *, host="host-a", harness="codex", native="native-a"):
    return {"session_id": session_id, "host_id": host, "harness": harness, "native_id": native}


def native(*, host="host-a", harness="codex", identity="native-a"):
    return {
        "host_id": host,
        "harness": harness,
        "native_id": identity,
        "source": "native_observation",
        "effective_state": "ACTIVE",
    }


def test_managed_and_native_share_one_exact_agent_row():
    rows = reconcile_observations([native()], [managed()])
    assert len(rows) == 1
    row = rows[0][1]
    assert row["identity_status"] == "VERIFIED" and row["source"] == "reconciled"
    assert row["effective_state"] == "ACTIVE"
    assert row["managed"][0]["session_id"] == "one"


@pytest.mark.parametrize(
    "binding",
    [
        managed(host="host-b"),
        managed(harness="claude"),
        managed(native="different"),
        managed(host=None),
        managed(harness=None),
        managed(native=None),
    ],
)
def test_incomplete_or_different_binding_cannot_merge(binding):
    rows = reconcile_observations([native()], [binding])
    assert len(rows) == 2
    assert all(row["identity_status"] != "VERIFIED" for _, row in rows)


def test_ambiguous_managed_binding_is_one_unknown_row_without_picking_a_winner():
    rows = reconcile_observations([native()], [managed(), managed("two")])
    assert len(rows) == 1
    assert rows[0][1]["identity_status"] == "AMBIGUOUS"
    assert rows[0][1]["effective_state"] == "UNKNOWN"
    assert {m["session_id"] for m in rows[0][1]["managed"]} == {"one", "two"}


def test_managed_report_has_no_invented_activity_timestamp():
    row = reconcile_observations([], [managed()])[0][1]
    assert row["identity_status"] == "MANAGED_LINK"
    assert row["effective_state"] == "UNKNOWN" and row["observed_at"] is None
