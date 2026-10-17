"""Dispatch an authorized browser connection to its terminal's transport."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, assert_never

from omnigent.terminals.attach_target import (
    ConPTYAttachTarget,
    TerminalAttachTarget,
    TmuxAttachTarget,
)

if TYPE_CHECKING:
    from fastapi import WebSocket


async def bridge_terminal_to_websocket(
    websocket: WebSocket,
    *,
    target: TerminalAttachTarget,
    read_only: bool,
    on_client_interaction: Callable[[], None] | None = None,
) -> None:
    """Attach without launching, replacing or closing the owned terminal."""
    if isinstance(target, TmuxAttachTarget):
        from omnigent.terminals.control_bridge import bridge_tmux_control_to_websocket

        await bridge_tmux_control_to_websocket(
            websocket,
            socket_path=str(target.socket_path),
            tmux_target=target.tmux_target,
            read_only=read_only,
            on_client_interaction=on_client_interaction,
        )
    elif isinstance(target, ConPTYAttachTarget):
        from omnigent.terminals.conpty_bridge import bridge_conpty_to_websocket

        await bridge_conpty_to_websocket(
            websocket,
            session=target.session,
            read_only=read_only,
            on_client_interaction=on_client_interaction,
        )
    else:
        assert_never(target)
