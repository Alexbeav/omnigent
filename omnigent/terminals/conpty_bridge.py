"""Experimental ConPTY adapter for the existing browser terminal framing.

Route authorization and session ownership remain the caller's responsibility.
Detaching/cancelling this adapter releases its subscription, never the terminal.
Native Windows launch remains gated independently of this adapter.
"""

from __future__ import annotations

import asyncio
import codecs
import json
import queue
from collections.abc import Callable
from contextlib import suppress

from fastapi import WebSocket, WebSocketDisconnect

from omnigent.terminals.conpty import ConPTYError, ConPTYSession, OutputOverflow
from omnigent.terminals.ws_common import (
    WS_CLOSE_INTERNAL_ERROR,
    WS_CLOSE_TERMINAL_DETACHED,
    WS_CLOSE_TERMINAL_NOT_FOUND,
)

_SEND_TIMEOUT_SECONDS = 5.0


async def bridge_conpty_to_websocket(
    websocket: WebSocket,
    *,
    session: ConPTYSession,
    read_only: bool,
    on_client_interaction: Callable[[], None] | None = None,
) -> None:
    """Stream an accepted, authorized WebSocket without owning the OS session."""
    viewer = session.subscribe()
    close_code = 1000
    close_reason = ""

    async def forward_output() -> None:
        nonlocal close_code, close_reason
        while True:
            try:
                # The timeout bounds a worker still unwinding after task cancellation.
                text = await asyncio.to_thread(viewer.read, 0.1)
            except queue.Empty:
                continue
            except OutputOverflow:
                close_code = WS_CLOSE_TERMINAL_DETACHED
                close_reason = "terminal viewer fell behind; reconnect"
                return
            if text is None:
                close_code = WS_CLOSE_TERMINAL_NOT_FOUND
                close_reason = "terminal session ended"
                return
            encoded = text.encode("utf-8")
            for offset in range(0, len(encoded), 65536):
                await asyncio.wait_for(
                    websocket.send_bytes(encoded[offset : offset + 65536]),
                    timeout=_SEND_TIMEOUT_SECONDS,
                )

    async def receive_input() -> None:
        decoder = codecs.getincrementaldecoder("utf-8")()
        while True:
            message = await websocket.receive()
            if on_client_interaction is not None:
                on_client_interaction()
            if message.get("type") == "websocket.disconnect":
                return
            if read_only:
                continue
            data = message.get("bytes")
            text = message.get("text")
            if data is not None:
                if len(data) > 4 * 1024 * 1024:
                    raise ConPTYError("Terminal input frame is too large.")
                decoded = decoder.decode(data)
                if decoded:
                    await asyncio.shield(asyncio.wrap_future(session.write(decoded)))
            elif text is not None:
                if len(text) > 1024:
                    continue
                try:
                    control = json.loads(text)
                except (ValueError, TypeError):
                    continue
                if not isinstance(control, dict) or control.get("type") != "resize":
                    continue
                rows, cols = control.get("rows"), control.get("cols")
                if type(rows) is not int or type(cols) is not int:
                    continue
                if not (1 <= rows <= 32767 and 1 <= cols <= 32767):
                    continue
                future = session.set_viewer_size(viewer, rows, cols)
                if future is not None:
                    await asyncio.shield(asyncio.wrap_future(future))

    output = asyncio.create_task(forward_output(), name="conpty-browser-output")
    input_task = asyncio.create_task(receive_input(), name="conpty-browser-input")
    tasks = {output, input_task}
    try:
        if on_client_interaction is not None:
            on_client_interaction()
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except (ConPTYError, UnicodeError):
        close_code = WS_CLOSE_INTERNAL_ERROR
        close_reason = "terminal transport failed"
    except TimeoutError:
        close_code = WS_CLOSE_TERMINAL_DETACHED
        close_reason = "terminal viewer fell behind; reconnect"
    except (WebSocketDisconnect, OSError, RuntimeError):
        # The peer can disappear during receive, send or final close.
        pass
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        session.unsubscribe(viewer)
        if on_client_interaction is not None:
            on_client_interaction()
        with suppress(WebSocketDisconnect, OSError, RuntimeError):
            await websocket.close(code=close_code, reason=close_reason)
