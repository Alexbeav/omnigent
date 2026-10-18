"""Bounded metadata sent by passive readers in an existing host daemon."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

NATIVE_HARNESSES = ("claude", "codex", "cline")
MAX_OBSERVATIONS = 2000
MAX_SNAPSHOT_BYTES = 1_048_576
OBSERVATION_TTL_S = 120
MAX_CLOCK_LEAD_S = 5

NativeHarness = Literal["claude", "codex", "cline"]
NativeId = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]
Epoch = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
Count = Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]


class NativeObservation(BaseModel):
    """A native fact, not a refreshed copy of an earlier activity event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    native_id: NativeId
    parent_native_id: NativeId | None = None
    surface: Literal["cli", "desktop", "editor", "unknown"] = "unknown"
    launch_origin: Literal["managed", "standalone", "unknown"] = "unknown"
    state: Literal["ACTIVE", "IDLE", "WAITING", "ERROR", "UNKNOWN"]
    observed_at: Epoch | None = None
    event: Literal[
        "session_start",
        "turn_start",
        "turn_end",
        "activity",
        "waiting",
        "error",
        "session_end",
        "unknown",
    ]
    present: bool = Field(default=True, strict=True)
    context_tokens: Count | None = None
    context_window: Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)] | None = None
    context_observed_at: Epoch | None = None


def quarantine_future_facts(row: NativeObservation, received_at: float) -> NativeObservation:
    """Discard unqualified future facts without replacing their evidence time."""
    changes = {}
    if row.observed_at is not None and row.observed_at > received_at + MAX_CLOCK_LEAD_S:
        changes.update(state="UNKNOWN", event="unknown", observed_at=None, present=True)
    if (
        row.context_observed_at is not None
        and row.context_observed_at > received_at + MAX_CLOCK_LEAD_S
    ):
        changes.update(context_tokens=None, context_window=None, context_observed_at=None)
    return row.model_copy(update=changes)


class NativeObservationSnapshot(BaseModel):
    """One harness inventory. Scan time never replaces a row's evidence time."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    harness: NativeHarness
    epoch: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    sequence: Count
    scanned_at: Epoch
    status: Literal["CURRENT", "PARTIAL", "UNAVAILABLE", "NOT_SUPPORTED", "DISABLED"]
    complete: bool = Field(strict=True)
    capabilities: list[Literal["discovery", "lifecycle", "waiting", "usage"]] = Field(
        default_factory=list, max_length=4
    )
    observations: list[NativeObservation] = Field(
        default_factory=list, max_length=MAX_OBSERVATIONS
    )

    @model_validator(mode="after")
    def bounded_inventory(self, info: ValidationInfo) -> NativeObservationSnapshot:
        ids = [row.native_id for row in self.observations]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate native observation identity")
        if self.status != "CURRENT" and self.complete:
            raise ValueError("Only a current inventory can establish absence")
        retained = bool(info.context and info.context.get("retained_facts"))
        for row in self.observations:
            # Stored facts were qualified on ingestion; current capabilities may shrink.
            if not retained and row.state != "UNKNOWN" and "lifecycle" not in self.capabilities:
                raise ValueError("Lifecycle evidence is not advertised")
            if not retained and row.state == "WAITING" and "waiting" not in self.capabilities:
                raise ValueError("Human-wait evidence is not advertised")
            if (
                not retained
                and (
                    row.context_tokens is not None
                    or row.context_window is not None
                    or row.context_observed_at is not None
                )
                and ("usage" not in self.capabilities)
            ):
                raise ValueError("Usage evidence is not advertised")
            if (
                row.observed_at is not None
                and row.observed_at > self.scanned_at + MAX_CLOCK_LEAD_S
            ):
                raise ValueError("Observation is later than its source scan")
            if (
                row.context_observed_at is not None
                and row.context_observed_at > self.scanned_at + MAX_CLOCK_LEAD_S
            ):
                raise ValueError("Context evidence is later than its source scan")
        if len(self.model_dump_json().encode("utf-8")) > MAX_SNAPSHOT_BYTES:
            raise ValueError("Native observation snapshot exceeds the metadata bound")
        return self
