"""Strict metadata contract for physical resource measurements."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from omnigent.native_observations import Count, Epoch

RESOURCE_TTL_S = 90
Percent = Annotated[float, Field(strict=True, ge=0, le=100, allow_inf_nan=False)]


class ResourceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MemoryMeasurement(ResourceModel):
    total_bytes: Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]
    available_bytes: Count
    used_percent: Percent

    @model_validator(mode="after")
    def consistent(self) -> MemoryMeasurement:
        expected = 100 * (self.total_bytes - self.available_bytes) / self.total_bytes
        if self.available_bytes > self.total_bytes or abs(expected - self.used_percent) > 0.01:
            raise ValueError("Inconsistent physical memory measurement")
        return self


class GpuMeasurement(ResourceModel):
    index: Annotated[int, Field(strict=True, ge=0, le=31)]
    vendor: Literal["nvidia", "amd"]
    utilization_percent: Percent | None
    memory_used_bytes: Count | None
    memory_total_bytes: Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)] | None
    memory_kind: Literal["dedicated", "unknown"]

    @model_validator(mode="after")
    def consistent(self) -> GpuMeasurement:
        used, total = self.memory_used_bytes, self.memory_total_bytes
        if (used is None) != (total is None) or (
            used is not None and total is not None and used > total
        ):
            raise ValueError("Inconsistent GPU memory measurement")
        return self


class GpuMeasurements(ResourceModel):
    status: Literal["CURRENT", "PARTIAL", "UNKNOWN", "UNSUPPORTED"]
    reason: (
        Literal[
            "GPU_QUERY_FAILED",
            "GPU_METRICS_INCOMPLETE",
            "GPU_MEMORY_NOT_QUALIFIED",
            "GPU_ADAPTER_NOT_IMPLEMENTED",
            "GPU_SENSOR_UNAVAILABLE",
        ]
        | None
    )
    devices: list[GpuMeasurement] = Field(max_length=32)
    observed_at: str | None = Field(default=None, max_length=64)


class ResourceSample(ResourceModel):
    schema_version: Literal[1]
    status: Literal["CURRENT", "PARTIAL", "UNAVAILABLE"]
    observed_at: str = Field(max_length=64)
    cpu_percent: Percent | None
    cpu_observed_at: str | None = Field(max_length=64)
    cpu_interval_seconds: Annotated[float, Field(strict=True, ge=0.25, le=0.25)]
    memory: MemoryMeasurement | None
    memory_observed_at: str | None = Field(max_length=64)
    memory_definition: Literal["100 * (physical total - OS available) / physical total"]
    gpu: GpuMeasurements

    @model_validator(mode="after")
    def evidence_times(self) -> ResourceSample:
        def timestamp(value: str) -> float:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None or parsed.timestamp() < 0:
                raise ValueError("Explicit UTC offset required")
            return parsed.timestamp()

        observed = timestamp(self.observed_at)
        for value in (self.cpu_observed_at, self.memory_observed_at, self.gpu.observed_at):
            if value is not None and timestamp(value) > observed + 5:
                raise ValueError("Resource evidence is later than its sample")
        if (self.cpu_percent is None) != (self.cpu_observed_at is None) or (
            self.memory is None
        ) != (self.memory_observed_at is None):
            raise ValueError("Measurement and source time must be paired")
        expected = (
            "CURRENT"
            if self.cpu_percent is not None and self.memory is not None
            else "PARTIAL"
            if self.cpu_percent is not None or self.memory is not None
            else "UNAVAILABLE"
        )
        if self.status != expected:
            raise ValueError("Resource status contradicts measurements")
        if len({d.index for d in self.gpu.devices}) != len(self.gpu.devices):
            raise ValueError("Duplicate GPU identity")
        if self.gpu.devices and self.gpu.observed_at is None:
            raise ValueError("GPU evidence time is required")
        if self.gpu.status in {"UNKNOWN", "UNSUPPORTED"} and self.gpu.devices:
            raise ValueError("Unavailable GPU cannot report measurements")
        if self.gpu.status == "CURRENT" and (
            not self.gpu.devices
            or self.gpu.reason is not None
            or any(
                d.utilization_percent is None or d.memory_total_bytes is None
                for d in self.gpu.devices
            )
        ):
            raise ValueError("Current GPU requires complete qualified measurements")
        if self.gpu.status == "PARTIAL" and not self.gpu.devices:
            raise ValueError("Partial GPU requires at least one measurement")
        return self


class HostResourceSnapshot(ResourceModel):
    version: Literal[1] = 1
    epoch: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    sequence: Count
    scanned_at: Epoch
    environment: Literal["native", "wsl"]
    sample: ResourceSample

    @model_validator(mode="after")
    def bounded(self) -> HostResourceSnapshot:
        if abs(datetime.fromisoformat(self.sample.observed_at).timestamp() - self.scanned_at) > 5:
            raise ValueError("Sample time differs from source scan")
        if len(self.model_dump_json().encode()) > 16384:
            raise ValueError("Resource metadata exceeds its bound")
        return self
