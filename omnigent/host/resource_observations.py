"""Bounded read-only hardware sampling. No task lifecycle or transport integration."""

from __future__ import annotations

import csv
import math
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _number(value: object, maximum: float | None = None) -> float | None:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0 or (maximum is not None and parsed > maximum):
        return None
    return parsed


def _gpu_sample() -> dict[str, Any]:
    executable = shutil.which("nvidia-smi")
    if executable:
        try:
            result = subprocess.run(
                [
                    executable,
                    "--query-gpu=index,utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=2,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if sys.platform == "win32"
                else 0,
                check=False,
            )
            if result.returncode != 0 or len(result.stdout) > 8192:
                return {"status": "UNKNOWN", "reason": "GPU_QUERY_FAILED", "devices": []}
            devices = []
            for row in list(csv.reader(result.stdout.splitlines()))[:32]:
                if len(row) != 4:
                    continue
                index = _number(row[0], 31)
                if index is None or not index.is_integer():
                    continue
                used, total = _number(row[2]), _number(row[3])
                valid_memory = (
                    used is not None and total is not None and total > 0 and used <= total
                )
                devices.append(
                    {
                        "index": int(index),
                        "vendor": "nvidia",
                        "utilization_percent": _number(row[1], 100),
                        "memory_used_bytes": int(used * 1024**2)
                        if valid_memory and used is not None
                        else None,
                        "memory_total_bytes": int(total * 1024**2)
                        if valid_memory and total is not None
                        else None,
                        "memory_kind": "dedicated" if valid_memory else "unknown",
                    }
                )
            complete = devices and all(
                d["utilization_percent"] is not None and d["memory_total_bytes"] is not None
                for d in devices
            )
            return {
                "status": "CURRENT" if complete else "PARTIAL" if devices else "UNKNOWN",
                "reason": None if complete else "GPU_METRICS_INCOMPLETE",
                "devices": devices,
                "observed_at": _now(),
            }
        except (OSError, subprocess.SubprocessError):
            return {"status": "UNKNOWN", "reason": "GPU_QUERY_FAILED", "devices": []}
    if sys.platform == "linux":
        devices = []
        for path in sorted(Path("/sys/class/drm").glob("card[0-9]*/device/gpu_busy_percent"))[:32]:
            try:
                vendor = (path.parent / "vendor").read_text(encoding="ascii").strip()
                if vendor != "0x1002":
                    continue
                with path.open(encoding="ascii") as stream:
                    utilization = _number(stream.read(65).strip(), 100)
                if utilization is not None:
                    devices.append(
                        {
                            "index": len(devices),
                            "vendor": "amd",
                            "utilization_percent": utilization,
                            "memory_used_bytes": None,
                            "memory_total_bytes": None,
                            "memory_kind": "unknown",
                        }
                    )
            except (OSError, UnicodeError):
                continue
        if devices:
            return {
                "status": "PARTIAL",
                "reason": "GPU_MEMORY_NOT_QUALIFIED",
                "devices": devices,
                "observed_at": _now(),
            }
    return {
        "status": "UNSUPPORTED" if sys.platform == "darwin" else "UNKNOWN",
        "reason": "GPU_ADAPTER_NOT_IMPLEMENTED"
        if sys.platform == "darwin"
        else "GPU_SENSOR_UNAVAILABLE",
        "devices": [],
    }


def sample_host_resources() -> dict[str, Any]:
    """Measure a 250ms CPU interval and RAM, plus optional driver counters.

    Run in an owned worker thread if integrated into a daemon. CPU/RAM failures
    remain unknown. Host identity must come from the authenticated transport.
    """
    cpu: float | None = None
    memory: dict[str, int | float] | None = None
    cpu_observed_at = memory_observed_at = None
    try:
        cpu = _number(psutil.cpu_percent(interval=0.25), 100)
        if cpu is not None:
            cpu_observed_at = _now()
    except (OSError, psutil.Error):
        pass
    try:
        value = psutil.virtual_memory()
        if value.total > 0 and 0 <= value.available <= value.total:
            memory = {
                "total_bytes": int(value.total),
                "available_bytes": int(value.available),
                "used_percent": round(100 * (value.total - value.available) / value.total, 3),
            }
            memory_observed_at = _now()
    except (OSError, psutil.Error):
        pass
    return {
        "schema_version": 1,
        "status": "CURRENT"
        if cpu is not None and memory is not None
        else "PARTIAL"
        if cpu is not None or memory is not None
        else "UNAVAILABLE",
        "observed_at": _now(),
        "cpu_percent": cpu,
        "cpu_observed_at": cpu_observed_at,
        "cpu_interval_seconds": 0.25,
        "memory": memory,
        "memory_observed_at": memory_observed_at,
        "memory_definition": "100 * (physical total - OS available) / physical total",
        "gpu": _gpu_sample(),
    }
