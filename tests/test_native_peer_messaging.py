"""Generated native chat agents keep the same-owner peer messaging grant."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

from omnigent.spec import load
from omnigent.tools.builtins.spawn import SysSessionSendTool


@pytest.mark.parametrize(
    ("native", "kwargs"),
    [
        ("antigravity", {}),
        ("claude", {}),
        ("codex", {"model": None}),
        ("cursor", {}),
        ("devin", {}),
        ("goose", {}),
        ("hermes", {}),
        ("kimi", {}),
        ("kiro", {}),
        ("opencode", {}),
        ("pi", {}),
        ("qwen", {}),
    ],
)
def test_generated_native_chat_grants_peer_messaging(
    native: str, kwargs: dict[str, Any], tmp_path: Path
) -> None:
    module = importlib.import_module(f"omnigent.harnesses.{native}_native.main")
    materialize = getattr(module, f"_materialize_{native}_agent_spec")

    spec = load(materialize(tmp_path, **kwargs))
    schema = SysSessionSendTool({}, peer_messaging=spec.peer_messaging).get_schema()["function"]

    assert spec.peer_messaging is True
    assert "Peer messaging is enabled" in schema["description"]
    assert "same owner" in schema["parameters"]["properties"]["session_id"]["description"]
