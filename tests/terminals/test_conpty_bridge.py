"""Browser framing at the ConPTY adapter boundary, without a server or provider."""

from __future__ import annotations

import asyncio

import pytest

from omnigent.terminals import conpty_bridge
from omnigent.terminals.conpty import ConPTYSession
from omnigent.terminals.ws_common import (
    WS_CLOSE_TERMINAL_DETACHED,
    WS_CLOSE_TERMINAL_NOT_FOUND,
)
from tests.terminals.test_conpty import _Driver
from tests.terminals.test_control_bridge import _FakeWebSocket


class _DrainedInputWebSocket(_FakeWebSocket):
    def __init__(self, inbound: list[dict[str, object]]) -> None:
        super().__init__(inbound)
        self.inputs_drained = asyncio.Event()

    async def receive(self) -> dict[str, object]:
        if not self._inbound:
            self.inputs_drained.set()
        return await super().receive()


@pytest.mark.parametrize("read_only", [False, True])
async def test_browser_input_resize_output_and_terminal_exit(read_only: bool) -> None:
    driver = _Driver()
    session = ConPTYSession(driver)
    greek = "λ".encode()
    ws = _DrainedInputWebSocket(
        inbound=[
            {"type": "websocket.receive", "bytes": greek[:1]},
            {"type": "websocket.receive", "bytes": greek[1:]},
            {"type": "websocket.receive", "bytes": b"\r"},
            {"type": "websocket.receive", "text": '{"type":"resize","cols":100,"rows":30}'},
        ]
    )
    bridge = asyncio.create_task(
        conpty_bridge.bridge_conpty_to_websocket(ws, session=session, read_only=read_only)
    )
    try:
        await asyncio.wait_for(ws.inputs_drained.wait(), timeout=1)
        await asyncio.wrap_future(session.resize(31, 101))
        driver.output.put("Καλημέρα\r\nfinal")
        driver.status = 7
        driver.alive = False
        await asyncio.wait_for(bridge, timeout=2)
        assert b"".join(ws.sent).decode() == "Καλημέρα\r\nfinal"
        assert ws.close_code == WS_CLOSE_TERMINAL_NOT_FOUND
        assert session.exit_status == 7
        if read_only:
            assert driver.operations == [(31, 101)]
        else:
            assert driver.operations == ["λ", "\r", (30, 100), (31, 101)]
    finally:
        bridge.cancel()
        await asyncio.gather(bridge, return_exceptions=True)
        session.close()
    assert not session.workers_alive


async def test_detach_and_outer_cancellation_preserve_terminal() -> None:
    driver = _Driver()
    session = ConPTYSession(driver)
    try:
        ws = _FakeWebSocket(inbound=[{"type": "websocket.disconnect"}])
        await conpty_bridge.bridge_conpty_to_websocket(ws, session=session, read_only=False)
        assert driver.alive and not driver.closed
        assert not session._subscribers
        ws = _FakeWebSocket(inbound=[])
        bridge = asyncio.create_task(
            conpty_bridge.bridge_conpty_to_websocket(ws, session=session, read_only=False)
        )
        await asyncio.sleep(0)
        bridge.cancel()
        with pytest.raises(asyncio.CancelledError):
            await bridge
        assert driver.alive and not driver.closed
        assert not session._subscribers
        session.write("after reconnect").result(timeout=1)
        assert driver.operations == ["after reconnect"]
    finally:
        session.close()
    assert not session.workers_alive


async def test_stalled_viewer_times_out_without_closing_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(conpty_bridge, "_SEND_TIMEOUT_SECONDS", 0.01)
    driver = _Driver()
    session = ConPTYSession(driver)
    ws = _FakeWebSocket(inbound=[], send_delay_s=60)
    try:
        driver.output.put("output")
        await asyncio.wait_for(
            conpty_bridge.bridge_conpty_to_websocket(ws, session=session, read_only=False),
            timeout=1,
        )
        assert ws.close_code == WS_CLOSE_TERMINAL_DETACHED
        assert "reconnect" in (ws.close_reason or "")
        assert driver.alive and not driver.closed
        assert not session._subscribers
    finally:
        session.close()
    assert not session.workers_alive


def test_smallest_viewer_size_is_lifted_on_detach() -> None:
    driver = _Driver()
    session = ConPTYSession(driver)
    large = session.subscribe()
    small = session.subscribe()
    try:
        first = session.set_viewer_size(large, 50, 200)
        assert first is not None
        first.result(timeout=1)
        second = session.set_viewer_size(small, 24, 80)
        assert second is not None
        second.result(timeout=1)
        assert session.set_viewer_size(large, 50, 200) is None
        session.unsubscribe(small)
        session.write("barrier").result(timeout=1)
        assert driver.operations == [(50, 200), (24, 80), (50, 200), "barrier"]
        assert session.set_viewer_size(small, 10, 10) is None
    finally:
        session.close()
    assert not session.workers_alive
