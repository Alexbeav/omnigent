"""Peer messaging: ``sys_session_send`` to a session that is not a child.

The runner is the only gate for this grant (the server cannot see the
spec's ``peer_messaging:`` flag), so these tests drive the dispatcher
directly against a fake server and check what it posted — or that it
posted nothing.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest

from omnigent.runner import subagent_work, tool_dispatch
from omnigent.runner.tool_dispatch import _execute_subagent_tool, _send_to_existing_session
from omnigent.spec.types import AgentSpec

_CALLER = "conv_caller"
_PEER = "conv_peer"
_OWNER = 4
_EDIT = 2


@pytest.fixture(autouse=True)
def _fresh_peer_budget(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Each test starts with an unused send budget and the default limit."""
    monkeypatch.delenv("OMNIGENT_PEER_SENDS_PER_HOUR", raising=False)
    tool_dispatch._peer_send_times.clear()
    yield
    tool_dispatch._peer_send_times.clear()


class _FakeServer:
    """A two-session server that records every message posted to it."""

    def __init__(
        self,
        *,
        caller: dict[str, Any] | None = None,
        peer: dict[str, Any] | None = None,
    ) -> None:
        self.sessions: dict[str, dict[str, Any]] = {
            _CALLER: {
                "id": _CALLER,
                "agent_name": "cline",
                "title": "refactor auth",
                "parent_session_id": None,
                "permission_level": _OWNER,
                "labels": {},
                **(caller or {}),
            },
            _PEER: {
                "id": _PEER,
                "agent_name": "codex",
                "title": "review",
                "parent_session_id": None,
                "permission_level": _OWNER,
                "labels": {},
                **(peer or {}),
            },
        }
        self.posted: list[tuple[str, dict[str, Any]]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        parts = request.url.path.strip("/").split("/")
        session_id = parts[2] if len(parts) > 2 else ""
        if request.method == "GET" and len(parts) == 3:
            session = self.sessions.get(session_id)
            if session is None:
                return httpx.Response(404, json={"error": "not_found"})
            return httpx.Response(200, json=session)
        if request.method == "POST" and parts[-1] == "events":
            self.posted.append((session_id, json.loads(request.content)))
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(f"unexpected request {request.method} {request.url.path}")

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self.handler), base_url="http://server"
        )

    def posted_text(self) -> str:
        """Text of the single message this server received."""
        assert len(self.posted) == 1, self.posted
        return self.posted[0][1]["data"]["content"][0]["text"]


async def _send(server: _FakeServer, *, peer_messaging: bool, target: str = _PEER) -> Any:
    """One by-session-id send from the caller; JSON result, or the raw error text."""
    async with server.client() as client:
        raw = await _send_to_existing_session(
            target,
            "can you review the token refresh path?",
            server_client=client,
            conversation_id=_CALLER,
            peer_messaging=peer_messaging,
        )
    try:
        return json.loads(raw)
    except ValueError:
        return raw


@pytest.mark.asyncio
async def test_non_child_target_is_refused_without_the_grant() -> None:
    """Stock behaviour holds for every agent that did not opt in."""
    server = _FakeServer()

    out = await _send(server, peer_messaging=False)

    assert out["error"] == "session_out_of_tree"
    assert "child-only" in out["message"]
    assert server.posted == [], "a refused send must not reach the target"


@pytest.mark.asyncio
async def test_peer_send_delivers_a_message_that_names_the_sender() -> None:
    """The receiver must be able to tell a peer from the person it works for.

    The message lands with the user role (nothing else starts a turn), so
    the only thing separating it from the human's own words is the system
    line in front of it: who sent it, from which session, and how to answer.
    """
    server = _FakeServer()

    out = await _send(server, peer_messaging=True)

    assert out["kind"] == "peer_message"
    assert out["status"] == "delivered"
    assert out["conversation_id"] == _PEER
    target, event = server.posted[0]
    assert target == _PEER
    assert event["type"] == "message"
    assert event["data"]["role"] == "user"
    text = server.posted_text()
    assert text.startswith("[System: peer message from agent 'cline' in session conv_caller")
    assert '("refactor auth")' in text
    assert "not by a person" in text
    assert "session_id='conv_caller'" in text, "the receiver needs the address to answer"
    assert text.endswith("can you review the token refresh path?")


@pytest.mark.asyncio
async def test_peer_send_tracks_no_work_for_the_target() -> None:
    """A peer is not a child: its turn must not complete into the sender's inbox.

    The child path registers a work entry so the target's completion is
    delivered to its parent. Doing that for a peer would hijack the
    completions of a session the sender does not own the lifecycle of.
    """
    server = _FakeServer()

    await _send(server, peer_messaging=True)

    assert subagent_work.get_subagent_work(_PEER) is None


@pytest.mark.asyncio
async def test_envelope_does_not_quote_an_envelope_as_the_sender_title() -> None:
    """A reply must not carry the message it answers inside its own header.

    A session first woken by a peer message is auto-titled with that
    envelope. Seen on a live server: its reply then read "peer message
    from agent 'beta' ... ("[System: peer message from agent 'alpha' ...")".
    """
    server = _FakeServer(
        caller={"title": "[System: peer message from agent 'codex' in session conv_peer…"}
    )

    await _send(server, peer_messaging=True)

    header = server.posted_text().split("\n\n", 1)[0]
    assert header.count("[System:") == 1
    assert '("' not in header


@pytest.mark.asyncio
async def test_envelope_quotes_only_the_start_of_a_long_title() -> None:
    """An untitled session's title is its whole first message."""
    server = _FakeServer(caller={"title": "x" * 500})

    await _send(server, peer_messaging=True)

    header = server.posted_text().split("\n\n", 1)[0]
    assert f'("{"x" * 80}")' in header


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "caller_level,peer_level",
    [(_OWNER, _EDIT), (_EDIT, _OWNER), (_OWNER, 3)],
    ids=["peer-shared-with-me", "caller-shared-with-me", "peer-manage-only"],
)
async def test_peer_send_refused_unless_the_same_owner_holds_both(
    caller_level: int, peer_level: int
) -> None:
    """Access is not ownership: a session merely shared with the user is off limits."""
    server = _FakeServer(
        caller={"permission_level": caller_level}, peer={"permission_level": peer_level}
    )

    out = await _send(server, peer_messaging=True)

    assert out["error"] == "session_out_of_tree"
    assert "same owner" in out["message"]
    assert server.posted == []


@pytest.mark.asyncio
async def test_peer_send_allowed_on_a_single_user_server() -> None:
    """No permission store means one user, who holds every session."""
    server = _FakeServer(caller={"permission_level": None}, peer={"permission_level": None})

    out = await _send(server, peer_messaging=True)

    assert out["status"] == "delivered"
    assert len(server.posted) == 1


@pytest.mark.asyncio
async def test_peer_send_refused_past_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two agents answering each other must run out of budget, not loop."""
    monkeypatch.setenv("OMNIGENT_PEER_SENDS_PER_HOUR", "2")
    server = _FakeServer()

    first = await _send(server, peer_messaging=True)
    second = await _send(server, peer_messaging=True)
    third = await _send(server, peer_messaging=True)

    assert first["status"] == second["status"] == "delivered"
    assert third["error"] == "peer_send_limit_reached"
    assert "limit 2" in third["message"]
    assert len(server.posted) == 2, "the refused send must not reach the target"


@pytest.mark.asyncio
async def test_peer_send_budget_refills_as_the_window_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cap is a rolling hour, not a lifetime allowance for the session."""
    monkeypatch.setenv("OMNIGENT_PEER_SENDS_PER_HOUR", "1")
    clock = {"now": 1000.0}
    monkeypatch.setattr(tool_dispatch.time, "monotonic", lambda: clock["now"])
    server = _FakeServer()

    assert (await _send(server, peer_messaging=True))["status"] == "delivered"
    assert (await _send(server, peer_messaging=True))["error"] == "peer_send_limit_reached"
    clock["now"] += tool_dispatch._PEER_SEND_WINDOW_SECONDS
    assert (await _send(server, peer_messaging=True))["status"] == "delivered"


@pytest.mark.asyncio
async def test_failed_delivery_does_not_spend_the_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only a message the peer actually received counts against the cap."""
    monkeypatch.setenv("OMNIGENT_PEER_SENDS_PER_HOUR", "1")
    server = _FakeServer()
    accept = {"posts": False}
    inner = server.handler

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and not accept["posts"]:
            return httpx.Response(503, text="runner offline")
        return inner(request)

    server.handler = handler  # type: ignore[method-assign]

    failed = await _send(server, peer_messaging=True)
    accept["posts"] = True
    retried = await _send(server, peer_messaging=True)

    assert isinstance(failed, str) and "503" in failed
    assert retried["status"] == "delivered"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["", "abc", "0", "-5"])
async def test_unusable_limit_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    """A typo in the env var must neither lift the cap nor close the feature."""
    monkeypatch.setenv("OMNIGENT_PEER_SENDS_PER_HOUR", bad)

    assert tool_dispatch._peer_send_limit() == tool_dispatch._DEFAULT_PEER_SEND_LIMIT


@pytest.mark.asyncio
async def test_peer_send_to_self_is_refused() -> None:
    """A session messaging itself would start its own next turn."""
    server = _FakeServer()

    out = await _send(server, peer_messaging=True, target=_CALLER)

    assert out["error"] == "peer_send_to_self"
    assert server.posted == []


@pytest.mark.asyncio
async def test_peer_send_to_a_closed_session_is_refused() -> None:
    server = _FakeServer(peer={"labels": {"omnigent.closed": "true"}})

    out = await _send(server, peer_messaging=True)

    assert out["error"] == "session_closed"
    assert server.posted == []


@pytest.mark.asyncio
async def test_unknown_target_is_reported_before_any_peer_check() -> None:
    server = _FakeServer()

    out = await _send(server, peer_messaging=True, target="conv_missing")

    assert out == {"error": "session_not_found", "conversation_id": "conv_missing"}


@pytest.mark.asyncio
async def test_direct_child_keeps_the_tracked_path_even_with_the_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The grant adds a route for non-children; it must not reroute children.

    A child sent to as a peer would lose its work entry, and with it the
    completion the parent is waiting on.
    """
    server = _FakeServer(peer={"parent_session_id": _CALLER})

    async def _peer_path_must_not_run(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("a direct child was routed to the peer path")

    monkeypatch.setattr(tool_dispatch, "_send_to_peer_session", _peer_path_must_not_run)
    inner = server.handler

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            return httpx.Response(200, json={})
        return inner(request)

    server.handler = handler  # type: ignore[method-assign]
    try:
        out = await _send(server, peer_messaging=True)
        assert out["kind"] == "sub_agent"
        assert subagent_work.get_subagent_work(_PEER) is not None
        assert "[System: peer message" not in server.posted_text()
    finally:
        subagent_work.unregister_subagent_work_for_session(_PEER)


async def _dispatch(spec: AgentSpec, server: _FakeServer) -> Any:
    """Run the real tool entry point, so the spec flag is what decides."""
    async with server.client() as client:
        raw = await _execute_subagent_tool(
            {"session_id": _PEER, "args": "ping"},
            server_client=client,
            conversation_id=_CALLER,
            agent_spec=spec,
            session_inbox=asyncio.Queue(),
        )
    return json.loads(raw)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "spec_factory,expected",
    [
        (lambda: AgentSpec(spec_version=1, spawn=True), "session_out_of_tree"),
        (lambda: AgentSpec(spec_version=1, spawn=True, peer_messaging=True), None),
    ],
    ids=["spawn-alone-is-not-enough", "peer-messaging-opts-in"],
)
async def test_the_spec_flag_is_what_grants_peer_sends(
    spec_factory: Callable[[], AgentSpec], expected: str | None
) -> None:
    """``spawn`` and ``peer_messaging`` are separate authorities."""
    server = _FakeServer()

    out = await _dispatch(spec_factory(), server)

    assert out.get("error") == expected
    assert len(server.posted) == (0 if expected else 1)
