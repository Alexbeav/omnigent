"""Isolation, budgets, usage, cancellation, and unsupported-model contracts."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from omnigent.reply_suggestions import normalize_suggestion, recent_context
from omnigent.runner import reply_suggestions as replies
from omnigent.runner.background_titles.service import BackgroundTitleContext


def test_context_and_output_limits() -> None:
    messages = [("user", "old secret context")] + [("assistant", "a" * 10_000 + "end")] * 4
    prompt = recent_context(messages)
    assert len(prompt) <= 6_000
    assert "old secret context" not in prompt
    assert all(row["text"].endswith("end") for row in json.loads(prompt))
    assert normalize_suggestion("NONE") is None
    assert normalize_suggestion("x" * 301) is None
    assert normalize_suggestion('"Show the diff."') == "Show the diff."


def test_economy_model_is_advertised_and_never_falls_back_to_expensive() -> None:
    assert replies.economy_model([{"model": "expensive-test-model"}]) is None
    assert (
        replies.economy_model([{"model": "claude-haiku-test"}], "claude-native")
        == "claude-haiku-test"
    )
    assert replies.economy_model([{"model": "claude-opus-test"}], "claude-native") is None


def test_usage_survives_discarded_result_without_claiming_a_codex_token_cap() -> None:
    data = b"\n".join(
        [
            b'{"type":"item.completed","item":{"type":"agent_message","text":"Show the diff."}}',
            b'{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":80,"output_tokens":10}}',
        ]
    )
    result = replies.codex_result(data, model="test", usable=False)
    assert result.status == "unavailable" and result.text is None
    assert result.max_output_tokens is None
    assert result.usage == {
        "input_tokens": 20,
        "cache_read_input_tokens": 80,
        "output_tokens": 10,
        "total_tokens": 110,
    }
    result = replies.claude_result(
        json.dumps(
            {
                "type": "result",
                "result": "Show the diff.",
                "usage": {"input_tokens": 9, "output_tokens": 3, "cache_read_input_tokens": 4},
            }
        ).encode(),
        model="claude-haiku-test",
        usable=False,
    )
    assert result.text is None and result.usage["total_tokens"] == 16
    assert result.max_output_tokens == 256


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_claude_uses_session_launch_and_isolated_tools_and_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path, cancel: bool
) -> None:
    from omnigent.claude_launcher import resolve_claude_launch
    from omnigent.harnesses.claude_native.main import ClaudeNativeUcodeConfig
    from omnigent.inner import _proc

    captured: dict[str, Any] = {}
    release = asyncio.Event()
    started = asyncio.Event()
    cancelled = asyncio.Event()
    output = (
        b'{"type":"result","result":"Show the diff.","usage":{"input_tokens":9,"output_tokens":3}}'
    )

    class Process:
        returncode: int | None = None

        async def communicate(self):
            started.set()
            if cancel:
                await release.wait()
            else:
                self.returncode = 0
            return output, None

    process = Process()

    async def spawn(*args, **kwargs):
        captured.update(args=args, **kwargs)
        return process

    def kill(child):
        assert child is process
        process.returncode = -9
        release.set()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(_proc, "kill_tree", kill)
    # Launch resolution stays native; replace only command discovery for this unit test.
    monkeypatch.setattr(
        "omnigent.claude_launcher.resolve_claude_launch", lambda command, args: (command, args)
    )
    assert callable(resolve_claude_launch)
    config = ClaudeNativeUcodeConfig(
        env={"ANTHROPIC_BASE_URL": "https://session-provider.test"},
        api_key_helper="session-auth-helper",
    )
    context = BackgroundTitleContext(
        prompt="[]", harness="claude-native", spawn_env={}, process_manager=SimpleNamespace()
    )
    task = asyncio.create_task(
        replies.generate_claude_reply_suggestion(context, "claude-haiku-test", config, cancelled)
    )
    await started.wait()
    if cancel:
        cancelled.set()
    result = await task
    args = captured["args"]
    assert "--safe-mode" in args and args[args.index("--tools") + 1] == ""
    assert "--no-session-persistence" in args
    assert args[args.index("--max-turns") + 1] == "1"
    settings = json.loads(args[args.index("--settings") + 1])
    assert settings["apiKeyHelper"] == "session-auth-helper"
    assert settings["disableAllHooks"] is True and settings["fallbackModel"] == []
    assert (
        captured["cwd"] != str(tmp_path)
        and not __import__("pathlib").Path(captured["cwd"]).exists()
    )
    assert captured["env"]["ANTHROPIC_BASE_URL"] == "https://session-provider.test"
    assert captured["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "256"
    assert captured["env"]["CLAUDE_CODE_MAX_RETRIES"] == "0"
    assert "ANTHROPIC_API_KEY" not in captured["env"]
    assert result.usage["output_tokens"] == 3
    assert (result.status == "unavailable") is cancel


@pytest.mark.asyncio
async def test_unsupported_harness_never_discovers_models_or_generates() -> None:
    async def context(_session, _body):
        return BackgroundTitleContext(
            prompt="[]", harness="acp", spawn_env={}, process_manager=SimpleNamespace()
        )

    async def no_models(*_args):
        raise AssertionError("unsupported harness must not discover or generate")

    app = FastAPI()
    replies.register_reply_suggestion_routes(
        app, resolve_context=context, model_options=no_models, resolve_claude_config=no_models
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://runner"
    ) as client:
        response = await client.post(
            "/v1/sessions/test/next-reply",
            json={
                "enabled": True,
                "source_response_id": "r1",
                "request_id": "one",
                "prompt": "[]",
            },
        )
    assert response.json()["status"] == "unsupported"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai", "gateway"])
async def test_codex_resolves_exact_session_account_and_disables_tools(monkeypatch, provider):
    from pathlib import Path

    import tomllib

    from omnigent.harnesses.codex_native import app_server
    from omnigent.inner import codex_executor

    session_spec = object()
    captured = {}

    def resolve(*, model, spec):
        assert spec is session_spec and model == "economy-test"
        return SimpleNamespace(model=model, profile="session-profile", config_overrides=[])

    def build(**kwargs):
        assert kwargs["profile"] == "session-profile"
        overrides = [f'model_provider="{provider}"']
        if provider == "gateway":
            overrides.append(
                'model_providers.gateway={name="Session gateway",'
                'base_url="https://session-provider.test",wire_api="responses"}'
            )
        return SimpleNamespace(codex_path="test-codex", env={}, config_overrides=overrides)

    class Process:
        returncode = 0

        async def communicate(self):
            return b'{"type":"turn.completed","usage":{"input_tokens":5,"output_tokens":2}}', None

    async def spawn(*args, **kwargs):
        captured.update(args=args, **kwargs)
        config_path = Path(kwargs["env"]["CODEX_HOME"]) / "config.toml"
        captured["config"] = tomllib.loads(config_path.read_text()) if config_path.exists() else {}
        return Process()

    monkeypatch.setattr(app_server, "resolve_native_codex_launch", resolve)
    monkeypatch.setattr(app_server, "build_codex_native_server", build)
    monkeypatch.setattr(codex_executor, "_populate_codex_home_config", lambda *_a, **_kw: None)
    monkeypatch.setattr(codex_executor, "_codex_home_config_source_from_env", lambda: None)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    context = BackgroundTitleContext(
        prompt="[]",
        harness="codex-native",
        spawn_env={},
        process_manager=SimpleNamespace(),
        session_spec=session_spec,
    )
    result = await replies.generate_reply_suggestion(context, "economy-test", asyncio.Event())
    args = captured["args"]
    assert "--ephemeral" in args and "--ignore-rules" in args
    assert "mcp_servers={}" in args and "tools.view_image=false" in args
    assert "features.shell_tool=false" in args and "features.unified_exec=false" in args
    assert f'model_provider="{provider}"' in args
    assert not any(arg.startswith("model_providers.") for arg in args)
    providers = captured["config"].get("model_providers", {})
    assert "openai" not in providers
    if provider == "gateway":
        assert providers["gateway"]["base_url"] == "https://session-provider.test"
        assert providers["gateway"]["request_max_retries"] == 0
        assert providers["gateway"]["stream_max_retries"] == 0
    assert result.usage["output_tokens"] == 2 and result.max_output_tokens is None


@pytest.mark.asyncio
@pytest.mark.parametrize("outer_deadline", [False, True])
async def test_timeout_kills_process_and_still_drains_reported_usage(monkeypatch, outer_deadline):
    from omnigent.inner import _proc

    released = asyncio.Event()

    class Process:
        returncode = None

        async def communicate(self):
            await released.wait()
            return b'{"type":"turn.completed","usage":{"input_tokens":5,"output_tokens":2}}', None

    process = Process()

    def kill(child):
        assert child is process
        child.returncode = -9
        released.set()

    monkeypatch.setattr(replies, "SUGGESTION_TIMEOUT_SECONDS", 12 if outer_deadline else 0.01)
    monkeypatch.setattr(_proc, "kill_tree", kill)
    async with asyncio.timeout(0.01 if outer_deadline else 1):
        data, usable = await replies.capture_process(process, asyncio.Event())
    result = replies.codex_result(data, model="economy-test", usable=usable)
    assert not usable and result.text is None
    assert result.usage["output_tokens"] == 2
