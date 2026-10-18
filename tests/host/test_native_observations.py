"""The passive wire contract rejects content and unsupported claims."""

import json

import pytest
from pydantic import ValidationError

from omnigent.host.frames import (
    HostNativeObservationsFrame,
    decode_host_frame,
    encode_host_frame,
)
from omnigent.native_observations import NativeObservationSnapshot


def snapshot(**changes):
    return NativeObservationSnapshot.model_validate(
        {
            "harness": "codex",
            "epoch": "a" * 32,
            "sequence": 1,
            "scanned_at": 1000,
            "status": "CURRENT",
            "complete": True,
            "capabilities": ["discovery", "lifecycle"],
            "observations": [
                {"native_id": "native-1", "state": "IDLE", "observed_at": 990, "event": "turn_end"}
            ],
            **changes,
        }
    )


def test_native_observation_frame_roundtrip_preserves_native_evidence_time():
    original = snapshot()
    decoded = decode_host_frame(encode_host_frame(HostNativeObservationsFrame(original)))
    assert isinstance(decoded, HostNativeObservationsFrame)
    assert decoded.snapshot == original
    assert decoded.snapshot.observations[0].observed_at == 990
    assert decoded.snapshot.observations[0].context_tokens is None


@pytest.mark.parametrize("field", ["prompt", "messages", "command", "cwd", "host_id", "owner"])
def test_native_observation_wire_rejects_unapproved_fields_without_echoing_values(field):
    body = snapshot().model_dump()
    body["observations"][0][field] = "privacy-canary-value"
    with pytest.raises(ValueError) as caught:
        decode_host_frame(json.dumps({"kind": "host.native_observations", "snapshot": body}))
    assert str(caught.value) == "Invalid native observation metadata"
    assert "privacy-canary-value" not in str(caught.value)


@pytest.mark.parametrize(
    "changes",
    [
        {"sequence": True},
        {"sequence": -1},
        {"scanned_at": float("nan")},
        {"scanned_at": "1000"},
        {"complete": "true"},
        {"epoch": "invalid"},
        {"status": "UNAVAILABLE"},
        {"capabilities": ["discovery"]},
    ],
)
def test_invalid_source_claim_is_rejected(changes):
    with pytest.raises(ValidationError):
        snapshot(**changes)


@pytest.mark.parametrize(
    "row_change",
    [
        {"native_id": "../private-path"},
        {"native_id": "x" * 129},
        {"observed_at": 2000},
        {"state": "WAITING", "event": "waiting"},
        {"context_tokens": 100},
    ],
)
def test_unproved_or_unbounded_native_claim_is_rejected(row_change):
    row = snapshot().observations[0].model_dump() | row_change
    with pytest.raises(ValidationError):
        snapshot(observations=[row])


def test_duplicate_and_oversized_inventories_are_rejected():
    row = snapshot().observations[0].model_dump()
    with pytest.raises(ValidationError, match="Duplicate"):
        snapshot(observations=[row, row])
    with pytest.raises(ValidationError):
        snapshot(observations=[row | {"native_id": str(i)} for i in range(2001)])
