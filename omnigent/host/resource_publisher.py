"""One bounded resource worker reused across host-tunnel reconnects."""

from __future__ import annotations

import asyncio
import logging
import platform
import secrets
from datetime import datetime
from typing import Any

from omnigent.host.frames import HostResourceObservationsFrame, encode_host_frame
from omnigent.host.resource_observations import sample_host_resources
from omnigent.host_resource_observations import HostResourceSnapshot

_logger = logging.getLogger(__name__)


class HostResourcePublisher:
    def __init__(self) -> None:
        self.epoch = secrets.token_hex(16)
        self.sequence = 0
        self._pending: asyncio.Task[dict[str, Any]] | None = None

    async def sample(self) -> HostResourceSnapshot:
        if self._pending is None:
            self._pending = asyncio.create_task(asyncio.to_thread(sample_host_resources))
        pending = self._pending
        try:
            async with asyncio.timeout(3):
                measured = await asyncio.shield(pending)
        finally:
            if pending.done():
                self._pending = None
        self.sequence += 1
        return HostResourceSnapshot.model_validate(
            {
                "epoch": self.epoch,
                "sequence": self.sequence,
                "scanned_at": datetime.fromisoformat(measured["observed_at"]).timestamp(),
                "environment": "wsl" if "microsoft" in platform.release().lower() else "native",
                "sample": measured,
            }
        )

    async def run(self, ws: Any) -> None:
        while True:
            try:
                snapshot = await self.sample()
                frame = encode_host_frame(HostResourceObservationsFrame(snapshot))
                async with asyncio.timeout(5):
                    await ws.send(frame)
            except Exception:  # noqa: BLE001 - optional telemetry must never stop a tunnel
                _logger.warning("Host resource publication unavailable; measurements will expire")
            await asyncio.sleep(30)
