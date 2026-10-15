"""What ``peer_messaging: true`` advertises to the agent.

Registration is advertisement, not authority (the runner enforces the
grant at dispatch; see ``tests/runner/test_peer_messaging.py``). These
tests pin that the flag adds exactly one thing to the tool surface and
that the schema tells the truth about what a peer send returns.
"""

from __future__ import annotations

from typing import Any

from omnigent.spec.types import AgentSpec
from omnigent.tools.manager import ToolManager


def _schemas(spec: AgentSpec) -> dict[str, dict[str, Any]]:
    return {s["function"]["name"]: s["function"] for s in ToolManager(spec).get_tool_schemas()}


def test_peer_messaging_defaults_off() -> None:
    assert AgentSpec(spec_version=1).peer_messaging is False


def test_bare_agent_gets_no_send_tool() -> None:
    assert "sys_session_send" not in _schemas(AgentSpec(spec_version=1))


def test_peer_messaging_alone_registers_send_and_nothing_else() -> None:
    """The grant is to message a peer, not to spawn or close anything."""
    tools = _schemas(AgentSpec(spec_version=1, peer_messaging=True))

    assert "sys_session_send" in tools
    assert "sys_session_create" not in tools
    assert "sys_session_close" not in tools
    assert "sys_list_models" not in tools


def test_peer_only_send_schema_offers_session_id_mode_only() -> None:
    """Without a spawn grant there is no sub-agent to name."""
    params = _schemas(AgentSpec(spec_version=1, peer_messaging=True))["sys_session_send"][
        "parameters"
    ]["properties"]

    assert "session_id" in params
    assert "agent" not in params
    assert "title" not in params


def test_schema_says_a_peer_send_returns_no_result() -> None:
    """The base description promises a result via sys_read_inbox.

    That promise is false for a peer send, and an agent that believes it
    waits on an inbox that never fills.
    """
    send = _schemas(AgentSpec(spec_version=1, spawn=True, peer_messaging=True))["sys_session_send"]

    assert "Peer messaging is enabled" in send["description"]
    assert "not a tracked dispatch" in send["description"]
    assert "same owner" in send["parameters"]["properties"]["session_id"]["description"]


def test_schema_is_unchanged_without_the_grant() -> None:
    """Agents that did not opt in must not be told about a route they lack."""
    send = _schemas(AgentSpec(spec_version=1, spawn=True))["sys_session_send"]

    assert "Peer messaging" not in send["description"]
    assert (
        "Must be a direct child" in send["parameters"]["properties"]["session_id"]["description"]
    )
