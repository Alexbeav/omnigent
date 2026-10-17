"""Development preflight rejects the broken exported-worker cases before tests."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "_development_toolchain", _ROOT / "scripts/check_development_toolchain.py"
)
assert _SPEC is not None and _SPEC.loader is not None
preflight = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(preflight)


def test_failed_executable_does_not_expose_its_output(tmp_path: Path) -> None:
    assert (
        preflight.command(
            [sys.executable, "-c", "import sys;print('private output');sys.exit(1)"], tmp_path
        )
        is None
    )
    assert preflight.command([str(tmp_path / "missing-binary")], tmp_path) is None
    assert preflight.command([sys.executable, "-c", "print('ready')"], tmp_path) == "ready"


def test_probe_timeout_returns_failure(tmp_path: Path) -> None:
    assert (
        preflight.command(
            [sys.executable, "-c", "import time;time.sleep(30)"], tmp_path, timeout=0.05
        )
        is None
    )


@pytest.mark.parametrize(
    "fault",
    [None, "missing-native-binary", "missing-typescript", "unborn-head", "wrong-source-sdk"],
)
def test_installed_metadata_cannot_hide_a_broken_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    (tmp_path / "uv.lock").write_text(
        "\n".join(
            f'[[package]]\nname = "{name}"\nversion = "1.0"'
            for name in ("pytest", "ruff", "pyrefly", "pre-commit")
        )
    )
    monkeypatch.setattr(preflight.importlib.metadata, "version", lambda _: "1.0")
    monkeypatch.setattr(preflight.shutil, "which", lambda name: name)
    monkeypatch.setattr(preflight, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(
        preflight, "sys", SimpleNamespace(version_info=(3, 12), executable=sys.executable)
    )
    locations = {
        "omnigent": "omnigent",
        "omnigent_client": "sdks/python-client/omnigent_client",
        "omnigent_ui_sdk": "sdks/ui/omnigent_ui_sdk",
    }

    original_spec = importlib.util.find_spec

    def spec(name):
        if name not in locations:
            return original_spec(name)
        source = tmp_path / locations[name] / "__init__.py"
        if name == "omnigent_client" and fault == "wrong-source-sdk":
            source = tmp_path / "installed/omnigent_client/__init__.py"
        return importlib.util.spec_from_file_location(name, source)

    monkeypatch.setattr(preflight.importlib.util, "find_spec", spec)

    def command(argv, root, **kwargs):
        if argv[:2] == ["git", "rev-parse"]:
            if argv[-1] == "--show-toplevel":
                return str(tmp_path)
            return None if fault == "unborn-head" else "a" * 40
        if argv[:2] == ["git", "cat-file"]:
            return ""
        if argv == ["node", "--version"]:
            return "v24.21.0"
        if argv[:2] == ["node", "-e"]:
            return None if fault == "missing-typescript" else "6.0.3"
        if "ruff" in argv and fault == "missing-native-binary":
            return None
        return "tool 1.0"

    monkeypatch.setattr(preflight, "command", command)
    result = preflight.check(tmp_path, "portable-checks")
    failures = [item["name"] for item in result["checks"] if not item["passed"]]
    if fault is None:
        assert result["passed"] and not failures
        return
    expected = {
        "missing-native-binary": "ruff-executable",
        "missing-typescript": "typescript",
        "unborn-head": "git-baseline",
        "wrong-source-sdk": "omnigent_client",
    }[fault]
    assert expected in failures and not result["passed"]


def test_missing_lockfile_reports_json_failure(tmp_path: Path, capsys) -> None:
    assert preflight.main(["--root", str(tmp_path)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert not result["passed"]
    assert result["checks"][-1]["name"] == "uv.lock"
