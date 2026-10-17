from subprocess import CompletedProcess, TimeoutExpired
from types import SimpleNamespace

import pytest

from omnigent.host import resource_observations as resources


@pytest.fixture(autouse=True)
def no_native_io(monkeypatch):
    monkeypatch.setattr(resources.psutil, "cpu_percent", lambda interval: 25)
    monkeypatch.setattr(
        resources.psutil, "virtual_memory", lambda: SimpleNamespace(total=10000, available=4000)
    )
    monkeypatch.setattr(resources.shutil, "which", lambda name: None)
    monkeypatch.setattr(resources.sys, "platform", "darwin")


def test_real_interval_and_memory_definition_do_not_assert_capacity():
    result = resources.sample_host_resources()
    assert result["status"] == "CURRENT"
    assert result["cpu_percent"] == 25
    assert result["cpu_interval_seconds"] == 0.25
    assert result["memory"]["used_percent"] == 60
    assert result["gpu"]["status"] == "UNSUPPORTED"
    assert "availability" not in result


def test_failed_measurements_stay_unknown_and_never_export_error_text(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("PRIVATE-CANARY")

    monkeypatch.setattr(resources.psutil, "cpu_percent", fail)
    monkeypatch.setattr(resources.psutil, "virtual_memory", fail)
    result = resources.sample_host_resources()
    assert result["status"] == "UNAVAILABLE"
    assert result["cpu_percent"] is None
    assert result["memory"] is None
    assert result["cpu_observed_at"] is None
    assert "PRIVATE-CANARY" not in str(result)


def test_invalid_sensor_values_are_not_clamped_into_valid_measurements(monkeypatch):
    monkeypatch.setattr(resources.psutil, "cpu_percent", lambda interval: float("nan"))
    monkeypatch.setattr(
        resources.psutil, "virtual_memory", lambda: SimpleNamespace(total=100, available=101)
    )
    assert resources.sample_host_resources()["status"] == "UNAVAILABLE"


def test_nvidia_uses_only_fixed_metadata_query_and_handles_unknown_counters(monkeypatch):
    monkeypatch.setattr(resources.shutil, "which", lambda name: "/fixture/nvidia-smi")
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return CompletedProcess(args, 0, "0, 42, 1024, 8192\n1, N/A, N/A, N/A\n", "PRIVATE-CANARY")

    monkeypatch.setattr(resources.subprocess, "run", run)
    result = resources.sample_host_resources()["gpu"]
    assert result["status"] == "PARTIAL"
    assert result["devices"][0]["memory_used_bytes"] == 1024**3
    assert result["devices"][1]["utilization_percent"] is None
    assert "PRIVATE-CANARY" not in str(result)
    assert calls[0][1]["timeout"] == 2
    assert calls[0][1]["encoding"] == "utf-8"
    assert "uuid" not in calls[0][0][1]


def test_gpu_timeout_does_not_discard_cpu_or_memory(monkeypatch):
    monkeypatch.setattr(resources.shutil, "which", lambda name: "/fixture/nvidia-smi")

    def fail(*args, **kwargs):
        raise TimeoutExpired("fixture", 2)

    monkeypatch.setattr(resources.subprocess, "run", fail)
    result = resources.sample_host_resources()
    assert result["status"] == "CURRENT"
    assert result["gpu"]["status"] == "UNKNOWN"


def test_amd_utilization_does_not_invent_dedicated_vram(monkeypatch, tmp_path):
    monkeypatch.setattr(resources.sys, "platform", "linux")
    root = tmp_path / "card0" / "device"
    root.mkdir(parents=True)
    (root / "gpu_busy_percent").write_text("12")
    (root / "vendor").write_text("0x1002")
    monkeypatch.setattr(resources, "Path", lambda path: tmp_path)
    result = resources.sample_host_resources()["gpu"]
    assert result["status"] == "PARTIAL"
    assert result["devices"][0]["utilization_percent"] == 12
    assert result["devices"][0]["memory_total_bytes"] is None
