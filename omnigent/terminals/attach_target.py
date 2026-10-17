"""Explicit browser attachment targets, independent of terminal ownership."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omnigent.terminals.conpty import ConPTYSession


@dataclass(frozen=True)
class TmuxAttachTarget:
    socket_path: Path
    tmux_target: str


@dataclass(frozen=True)
class ConPTYAttachTarget:
    session: ConPTYSession


TerminalAttachTarget = TmuxAttachTarget | ConPTYAttachTarget
