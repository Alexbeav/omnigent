"""Experimental managed Windows terminals; native harness readiness stays gated."""

from __future__ import annotations

import asyncio
import inspect
import os
import shutil
import tempfile
import threading
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path

from omnigent.inner.datamodel import OSEnvSpec, TerminalEnvSpec
from omnigent.inner.os_env import OSEnvironment, create_os_environment
from omnigent.inner.terminal import (
    _CLIENT_INTERACTION_WINDOW_SECONDS,
    TerminalCreateResult,
    TerminalInstance,
    TerminalResult,
    _IdleDetector,
    build_terminal_os_env_spec,
    terminal_pane_environment,
)
from omnigent.terminals import conpty
from omnigent.terminals.attach_target import ConPTYAttachTarget

_KEYS = {
    "Enter": "\r",
    "Tab": "\t",
    "Space": " ",
    "Escape": "\x1b",
    "BSpace": "\x7f",
    "Backspace": "\x7f",
    "BTab": "\x1b[Z",
    "Up": "\x1b[A",
    "Down": "\x1b[B",
    "Right": "\x1b[C",
    "Left": "\x1b[D",
    "Home": "\x1b[H",
    "End": "\x1b[F",
    "DC": "\x1b[3~",
    "Delete": "\x1b[3~",
    "IC": "\x1b[2~",
    "PageUp": "\x1b[5~",
    "PageDown": "\x1b[6~",
}


def _encode_keys(keys: str) -> str:
    result = []
    for key in keys.split():
        if key in _KEYS:
            result.append(_KEYS[key])
        elif len(key) == 3 and key[:2] == "C-" and key[2].isascii() and key[2].isalpha():
            result.append(chr(ord(key[2].lower()) - ord("a") + 1))
        else:
            raise ValueError("Unsupported Windows terminal key")
    return "".join(result)


class ConPTYTerminalInstance(TerminalInstance):
    """Adapt an owned ConPTY session to the managed terminal contract."""

    _session: conpty.ConPTYSession | None = None

    @property
    def attach_target(self) -> ConPTYAttachTarget:
        if self._session is None:
            raise RuntimeError("Windows terminal has not been launched")
        return self._session.attach_target

    async def launch(self, *, cwd: Path | None = None) -> None:
        if self._session is not None:
            if self._session.alive:
                return
            raise RuntimeError("Close the previous Windows terminal before relaunching")
        if self.sandbox_policy is not None and self.sandbox_policy.active:
            raise RuntimeError("Windows terminal sandbox launch is not qualified")
        if self.egress_rules or self.tmux_start_on_attach:
            raise RuntimeError("Windows terminal does not support this launch policy")
        try:
            launch_environment = self.lifecycle_trace.launch_environment(self.diagnostic_id)
        except Exception:
            launch_environment = {}
        overrides = (
            {key.upper(): value for key, value in os.environ.items()} if self.inherit_env else {}
        )
        overrides.update({key.upper(): value for key, value in self.env.items()})
        environment = terminal_pane_environment(
            inherit_env=False,
            env=overrides,
            env_unset=[key.upper() for key in self.env_unset],
            launch_environment=launch_environment,
        )
        excluded = {key.upper() for key in self.env_unset}
        environment = {
            key: value for key, value in environment.items() if key.upper() not in excluded
        }
        directory = cwd or self.private_dir
        self._session = conpty.spawn_conpty(
            [self.command, *self.args],
            cwd=directory,
            env=environment,
            capture_screen=True,
            scrollback=self.scrollback,
        )
        self.launch_cwd = str(directory)
        self.running = True

    async def send(self, text: str | None = None, *, keys: str = "Enter") -> TerminalResult:
        if self._session is None or not self._session.alive:
            return {"error": "Terminal is not running"}
        try:
            payload = (text or "") + _encode_keys(keys)
            if payload:
                await asyncio.wrap_future(self._session.write(payload))
        except (RuntimeError, ValueError):
            return {"error": "Windows terminal input failed; inspect before retrying"}
        return {"status": "sent"}

    async def read(self, scrollback: int = 0, *, join_wrapped: bool = False) -> TerminalResult:
        if self._session is None:
            return {"error": "Terminal has not been launched"}
        try:
            snapshot = self._session.capture(scrollback, join_wrapped=join_wrapped)
        except (RuntimeError, ValueError):
            return {"error": "Windows terminal screen capture is unavailable"}
        self._remember_pane_snapshot(snapshot.text)
        return {
            "terminal": f"{self.name}:{self.session_key}",
            "screen": snapshot.text,
            "scrollback_lines": snapshot.history_lines,
        }

    def _remember_exit(self) -> None:
        if self._session is not None and not self._session.alive:
            self._last_exit_status = self._session.exit_status
            with suppress(RuntimeError, ValueError):
                self._last_exit_snapshot = self._session.capture(min(self.scrollback, 100)).text

    async def is_alive(self) -> bool:
        alive = self._session is not None and self._session.alive
        if not alive:
            self._remember_exit()
            self.running = False
        return alive

    def pane_pid_sync(self) -> int | None:
        return self._session.pid if self._session is not None else None

    def last_exit_status(self) -> int | None:
        self._remember_exit()
        return self._last_exit_status

    async def set_conversation_link(self, conversation_link: str | None) -> None:
        self.conversation_link = conversation_link

    async def close(self) -> None:
        await self._stop_idle_watcher()
        await asyncio.to_thread(self._stop_idle_watcher_thread)
        if self._session is not None:
            await asyncio.to_thread(self._session.close)
            self._remember_exit()
        self.running = False
        if self.os_env is not None:
            self.os_env.close()
        shutil.rmtree(self.private_dir, ignore_errors=True)

    async def _idle_watch_loop(
        self,
        on_idle: Callable[[], None | Awaitable[None]],
        *,
        on_exit: Callable[[], None | Awaitable[None]] | None = None,
    ) -> None:
        detector = _IdleDetector()
        while True:
            await asyncio.sleep(0.2)
            if not await self.is_alive():
                if on_exit is not None:
                    result = on_exit()
                    if inspect.isawaitable(result):
                        await result
                return
            snapshot = await self.read()
            if "screen" in snapshot and detector.tick(
                snapshot["screen"],
                suppress_activity=self.client_interaction_within(
                    _CLIENT_INTERACTION_WINDOW_SECONDS
                ),
            ):
                result = on_idle()
                if inspect.isawaitable(result):
                    await result

    def _idle_watch_loop_threaded(
        self,
        stop_event: threading.Event,
        *,
        on_idle: Callable[[], None] | None = None,
        on_activity: Callable[[], None] | None = None,
        on_exit: Callable[[], None] | None = None,
        on_tick: Callable[[], None] | None = None,
        idle_threshold_s: float | None = None,
        poll_interval_s: float | None = None,
    ) -> None:
        detector = _IdleDetector(idle_threshold_s=idle_threshold_s)
        interval = poll_interval_s if poll_interval_s is not None else 0.2
        if interval <= 0:
            raise ValueError("Windows terminal poll interval must be positive")
        while not stop_event.wait(interval):
            session = self._session
            if session is None or not session.alive:
                self._remember_exit()
                self.running = False
                if on_exit is not None:
                    self._fire_watch_callback(on_exit, "exit")
                return
            if on_tick is not None and not self._fire_watch_callback(on_tick, "tick"):
                return
            try:
                snapshot = session.capture().text
            except (RuntimeError, ValueError):
                continue
            self._remember_pane_snapshot(snapshot)
            idle = detector.tick(
                snapshot,
                suppress_activity=self.client_interaction_within(
                    _CLIENT_INTERACTION_WINDOW_SECONDS
                ),
            )
            for callback, fire, kind in [
                (on_activity, detector.changed_this_tick, "activity"),
                (on_idle, idle, "idle"),
            ]:
                if callback is not None and fire and not self._fire_watch_callback(callback, kind):
                    return


def create_conpty_instance(
    name: str,
    session_key: str,
    spec: TerminalEnvSpec,
    *,
    parent_os_env_spec: OSEnvSpec | None = None,
    parent_environment: OSEnvironment | None = None,
    cwd_override: str | None = None,
    sandbox_override: str | None = None,
    conversation_link: str | None = None,
) -> TerminalCreateResult:
    effective = build_terminal_os_env_spec(
        spec,
        parent_os_env_spec=parent_os_env_spec,
        cwd_override=cwd_override,
        sandbox_override=sandbox_override,
    )
    sandbox = effective.sandbox
    if (
        effective.fork
        or effective.start_in_scratch
        or spec.tmux_start_on_attach
        or sandbox is None
        or (
            sandbox is not None
            and (
                sandbox.type != "none"
                or sandbox.egress_rules
                or any(path.copy_on_write for path in sandbox.write_path_specs)
            )
        )
        or (
            parent_environment is not None
            and getattr(getattr(parent_environment, "sandbox", None), "active", False)
        )
    ):
        raise ValueError("Windows terminal policy requires a separately qualified backend")
    cwd = Path(effective.cwd or os.getcwd()).resolve()
    if not cwd.is_dir():
        raise ValueError("Windows terminal working directory does not exist")
    os_env = create_os_environment(effective)
    private_dir = Path(tempfile.mkdtemp(prefix="omnigent-conpty-"))
    instance = ConPTYTerminalInstance(
        name=name,
        session_key=session_key,
        socket_path=None,
        private_dir=private_dir,
        os_env=os_env,
        command=spec.command or "powershell.exe",
        args=list(spec.args),
        env=dict(spec.env),
        env_unset=list(spec.env_unset),
        inherit_env=spec.inherit_env,
        scrollback=spec.scrollback,
        conversation_link=conversation_link,
        keep_alive_after_exit=spec.keep_alive_after_exit,
    )
    return TerminalCreateResult(instance=instance, cwd=cwd)
