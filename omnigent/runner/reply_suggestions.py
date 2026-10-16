"""One isolated native CLI request using the session's existing provider launch."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

from omnigent.models.model_fallbacks import REPLY_SUGGESTION_CODEX_MODELS

if TYPE_CHECKING:
    from omnigent.harnesses.claude_native.main import ClaudeNativeUcodeConfig

from omnigent.reply_suggestions import (
    SUGGESTION_INSTRUCTIONS,
    SUGGESTION_TIMEOUT_SECONDS,
    ReplySuggestionResult,
    RunnerReplySuggestionRequest,
    normalize_suggestion,
)
from omnigent.runner.background_titles.service import BackgroundTitleContext


def economy_model(rows: list[dict[str, Any]], harness: str = "codex-native") -> str | None:
    """Only select a known economy model actually advertised by this account."""
    if harness == "claude-native":
        return next(
            (str(row["model"]) for row in rows if "haiku" in str(row.get("model", "")).lower()),
            None,
        )
    available = {row.get("model") for row in rows}
    return next((model for model in REPLY_SUGGESTION_CODEX_MODELS if model in available), None)


def codex_result(stdout: bytes, *, model: str, usable: bool) -> ReplySuggestionResult:
    """Read only final text and usage. Never return raw CLI error output."""
    text = ""
    usage: dict[str, int | float] = {}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(event, dict):
            continue
        item = event.get("item", {})
        if event.get("type") == "item.completed" and item.get("type") == "agent_message":
            text = item.get("text", "")
        if event.get("type") == "turn.completed":
            raw = event.get("usage", {})
            for source, target in (
                ("input_tokens", "input_tokens"),
                ("output_tokens", "output_tokens"),
                ("cached_input_tokens", "cache_read_input_tokens"),
            ):
                value = raw.get(source)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    usage[target] = value
    # Codex input includes cached tokens. Omnigent's input bucket excludes them.
    if "input_tokens" in usage:
        total_input = usage["input_tokens"]
        usage["input_tokens"] = max(0, total_input - usage.get("cache_read_input_tokens", 0))
        usage["total_tokens"] = total_input + usage.get("output_tokens", 0)
    suggestion = normalize_suggestion(text) if usable else None
    return ReplySuggestionResult(
        status=("ready" if suggestion else "none") if usable else "unavailable",
        text=suggestion,
        model=model,
        usage=usage,
    )


async def generate_reply_suggestion(
    context: BackgroundTitleContext,
    model: str,
    cancelled: asyncio.Event,
) -> ReplySuggestionResult:
    """Never resume a real thread, run tools, or retry on another model."""
    from omnigent.harnesses.codex_native.app_server import (
        build_codex_native_server,
        resolve_native_codex_launch,
    )
    from omnigent.inner import _proc
    from omnigent.inner.codex_executor import (
        _codex_home_config_source_from_env,
        _populate_codex_home_config,
        materialize_codex_provider_config,
    )
    from omnigent.spec.types import RetryPolicy
    from omnigent.util.reasoning_effort import CODEX_NATIVE_EFFORTS

    launch = resolve_native_codex_launch(model=model, spec=context.session_spec)
    with tempfile.TemporaryDirectory(prefix="omnigent-next-reply-") as directory:
        root = Path(directory)
        home, workspace = root / "codex-home", root / "workspace"
        home.mkdir(mode=0o700)
        workspace.mkdir()
        _populate_codex_home_config(
            home,
            _codex_home_config_source_from_env(),
            minimal_config=True,
            supported_efforts=CODEX_NATIVE_EFFORTS,
        )
        server = await asyncio.to_thread(
            build_codex_native_server,
            socket_path=root / "unused.sock",
            codex_home=home,
            cwd=workspace,
            model=launch.model,
            profile=launch.profile,
            bridge_dir=root / "bridge",
            extra_config_overrides=launch.config_overrides,
        )
        # Built-in provider IDs are reserved. Only custom providers accept retry settings.
        overrides = materialize_codex_provider_config(
            home,
            server.config_overrides,
            retry_policy=RetryPolicy(max_retries=0, timeout_per_request_s=None),
        )
        instructions_file = root / "instructions.md"
        instructions_file.write_text(SUGGESTION_INSTRUCTIONS, encoding="utf-8")
        overrides += [
            f"model_instructions_file={json.dumps(str(instructions_file))}",
            'approval_policy="never"',
            'model_reasoning_effort="low"',
            'web_search="disabled"',
            'developer_instructions=""',
            "mcp_servers={}",
            "tools.view_image=false",
            "project_doc_max_bytes=0",
            "features.unified_exec=false",
            "features.shell_tool=false",
            "features.apps=false",
            "features.browser_use=false",
            "features.computer_use=false",
            "features.image_generation=false",
            "features.multi_agent=false",
            "features.plugins=false",
            "features.tool_search=false",
            "features.memories=false",
        ]
        args = [
            "exec",
            "--ephemeral",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--json",
            "--color",
            "never",
            "--model",
            model,
        ]
        for override in overrides:
            args.extend(("--config", override))
        args.append(f"{SUGGESTION_INSTRUCTIONS}\n<transcript>\n{context.prompt}\n</transcript>")
        if cancelled.is_set():
            return ReplySuggestionResult(status="unavailable")
        process = await asyncio.create_subprocess_exec(
            server.codex_path,
            *args,
            cwd=str(workspace),
            env={**server.env, "CODEX_HOME": str(home)},
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            **_proc.spawn_kwargs(),
        )
        stdout, usable = await capture_process(process, cancelled)
        return codex_result(stdout, model=model, usable=usable)


async def capture_process(process: Any, cancelled: asyncio.Event) -> tuple[bytes, bool]:
    from omnigent.inner import _proc

    communication = asyncio.create_task(process.communicate())
    cancellation = asyncio.create_task(cancelled.wait())
    usable = False
    try:
        done, _ = await asyncio.wait(
            {communication, cancellation},
            timeout=SUGGESTION_TIMEOUT_SECONDS,
            return_when=asyncio.FIRST_COMPLETED,
        )
        usable = communication in done and not cancelled.is_set()
    except asyncio.CancelledError:
        # The overall deadline must still drain any usage emitted before process death.
        usable = False
    finally:
        cancellation.cancel()
        if process.returncode is None:
            _proc.kill_tree(process)
        stdout, _ = await communication
        with contextlib.suppress(asyncio.CancelledError):
            await cancellation
    return stdout, usable and process.returncode == 0


def claude_result(stdout: bytes, *, model: str, usable: bool) -> ReplySuggestionResult:
    text = ""
    usage: dict[str, int | float] = {}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "result":
            text = event.get("result", "")
            raw = event.get("usage", {})
            for field in (
                "input_tokens",
                "output_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
            ):
                value = raw.get(field)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    usage[field] = value
            usable = usable and not event.get("is_error", False)
        elif event.get("type") == "assistant":
            message = event.get("message", {})
            for field, value in message.get("usage", {}).items():
                if (
                    field
                    in (
                        "input_tokens",
                        "output_tokens",
                        "cache_read_input_tokens",
                        "cache_creation_input_tokens",
                    )
                    and isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                ):
                    usage[field] = value
            if any(block.get("type") == "tool_use" for block in message.get("content", [])):
                usable = False
    if usage:
        usage["total_tokens"] = sum(usage.values())
    suggestion = normalize_suggestion(text) if usable else None
    return ReplySuggestionResult(
        status=("ready" if suggestion else "none") if usable else "unavailable",
        text=suggestion,
        model=model,
        usage=usage,
        max_output_tokens=256,
    )


async def generate_claude_reply_suggestion(
    context: BackgroundTitleContext,
    model: str,
    config: ClaudeNativeUcodeConfig | None,
    cancelled: asyncio.Event,
) -> ReplySuggestionResult:
    from omnigent.claude_launcher import resolve_claude_launch
    from omnigent.harnesses.claude_native.main import build_native_claude_terminal_env
    from omnigent.inner import _proc
    from omnigent.runner.native.orchestration import _claude_terminal_env_unset

    settings: dict[str, Any] = {"disableAllHooks": True, "fallbackModel": []}
    if config is not None:
        if config.api_key_helper:
            settings["apiKeyHelper"] = config.api_key_helper
        if config.model_overrides:
            settings["modelOverrides"] = config.model_overrides
    args = [
        "--safe-mode",
        "--tools",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--system-prompt",
        SUGGESTION_INSTRUCTIONS,
        "--settings",
        json.dumps(settings),
        "--setting-sources",
        "",
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        "--max-turns",
        "1",
        "--permission-prompts",
        "none",
        "--effort",
        "low",
        "--model",
        model,
        "-p",
        f"<transcript>\n{context.prompt}\n</transcript>",
    ]
    command, launch_args = resolve_claude_launch("claude", args)
    env = {**os.environ, **context.spawn_env, **build_native_claude_terminal_env(config)}
    for key in _claude_terminal_env_unset(config):
        env.pop(key, None)
    env.update(
        {
            "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "256",
            "MAX_THINKING_TOKENS": "0",
            "CLAUDE_CODE_MAX_RETRIES": "0",
            "CLAUDE_CODE_RETRY_WATCHDOG": "0",
            "CLAUDE_CODE_DISABLE_MODEL_ACCESS_FALLBACK": "1",
            "CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION": "false",
        }
    )
    with tempfile.TemporaryDirectory(prefix="omnigent-next-reply-") as workspace:
        if cancelled.is_set():
            return ReplySuggestionResult(status="unavailable")
        process = await asyncio.create_subprocess_exec(
            command,
            *launch_args,
            cwd=workspace,
            env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            **_proc.spawn_kwargs(),
        )
        stdout, usable = await capture_process(process, cancelled)
    return claude_result(stdout, model=model, usable=usable)


def register_reply_suggestion_routes(
    app: FastAPI,
    *,
    resolve_context: Callable[
        [str, RunnerReplySuggestionRequest], Awaitable[BackgroundTitleContext]
    ],
    model_options: Callable[[str, str], Awaitable[list[dict[str, Any]]]],
    resolve_claude_config: Callable[[str], Awaitable[ClaudeNativeUcodeConfig | None]],
) -> None:
    cancellations: dict[tuple[str, str], asyncio.Event] = {}

    @app.post("/v1/sessions/{session_id}/next-reply")
    async def generate(
        session_id: str, body: RunnerReplySuggestionRequest
    ) -> ReplySuggestionResult:
        key = (session_id, body.request_id)
        cancelled = cancellations.setdefault(key, asyncio.Event())
        try:
            async with asyncio.timeout(SUGGESTION_TIMEOUT_SECONDS + 5):
                context = await resolve_context(session_id, body)
                if context.harness not in ("codex-native", "claude-native"):
                    return ReplySuggestionResult(status="unsupported")
                if context.session_spec is None:
                    return ReplySuggestionResult(status="unsupported")
                model = economy_model(
                    await model_options(session_id, context.harness), context.harness
                )
                if model is None:
                    return ReplySuggestionResult(status="unsupported")
                if context.harness == "claude-native":
                    config = await resolve_claude_config(session_id)
                    return await generate_claude_reply_suggestion(
                        context, model, config, cancelled
                    )
                return await generate_reply_suggestion(context, model, cancelled)
        except (OSError, RuntimeError, TimeoutError):
            return ReplySuggestionResult(status="unavailable")
        finally:
            cancellations.pop(key, None)

    @app.delete("/v1/sessions/{session_id}/next-reply/{request_id}")
    async def cancel(session_id: str, request_id: str) -> dict[str, bool]:
        event = cancellations.get((session_id, request_id))
        if event is None and len(cancellations) < 256:
            event = cancellations.setdefault((session_id, request_id), asyncio.Event())
        if event is not None:
            event.set()
        return {"cancelled": event is not None}
