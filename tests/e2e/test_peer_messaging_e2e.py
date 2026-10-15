"""Two top-level sessions exchange a peer message and a reply.

The server, the runner, the openai-agents harness, tool dispatch and the
event transport are real. Only the model endpoint is scripted: it makes
one agent call ``sys_session_send`` at the other, and the other answer the
same way. Nothing is posted into either transcript by the test except the
single kickoff message a person would type.

Unit coverage of the refusals lives in ``tests/runner/test_peer_messaging.py``;
this is the one check that a peer message really starts a turn in a session
the sender did not create, on a server that computes ownership for itself.

Run: uv run --no-sync pytest tests/e2e/test_peer_messaging_e2e.py -v -s
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from tests._helpers.live_server import find_free_port, terminate_process
from tests._helpers.server_runner import server_runner
from tests._helpers.session import bind_session_runner, bundle_files, post_session_bundle

_REPO = Path(__file__).resolve().parents[2]
_KICKOFF = "PEER_E2E_KICKOFF: ask the reviewer session for its status."
_PING = "PEER_E2E_PING: what is the status of the token refresh review?"
_PONG = "PEER_E2E_PONG: review done, two findings, both fixed."
pytestmark = pytest.mark.timeout(360)


def _wait(check: Callable[[], Any], description: str, timeout: float = 120.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.5)
    raise AssertionError(f"Timed out waiting for {description}")


@pytest.fixture
def mock_model(tmp_path: Path) -> Iterator[str]:
    """A scripted model endpoint that only this test's two agents talk to."""
    port = find_free_port()
    url = f"http://127.0.0.1:{port}"
    with (tmp_path / "mock_llm.log").open("w") as log:
        proc = subprocess.Popen(
            [
                sys.executable,
                str(_REPO / "tests" / "server" / "integration" / "mock_llm_server.py"),
                str(port),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:

            def up() -> bool:
                try:
                    return httpx.get(f"{url}/stats", timeout=2, trust_env=False).status_code == 200
                except httpx.HTTPError:
                    return False

            _wait(up, "the mock model server", 30)
            yield url
        finally:
            terminate_process(proc)


def _agent_bundle(name: str, model: str, mock_url: str) -> bytes:
    spec = {
        "name": name,
        "prompt": f"You are {name}. Coordinate with peer sessions when asked.",
        "executor": {
            "model": model,
            "harness": "openai-agents",
            "auth": {"type": "api_key", "api_key": "mock-key", "base_url": f"{mock_url}/v1"},
        },
        # The only grant either agent holds: no spawn, no declared sub-agents.
        "peer_messaging": True,
        "os_env": {"type": "caller_process", "cwd": ".", "sandbox": {"type": "none"}},
    }
    return bundle_files({f"./{name}.yaml": yaml.safe_dump(spec, sort_keys=False).encode()})


def _script(mock_url: str, model: str, responses: list[dict[str, Any]]) -> None:
    httpx.post(
        f"{mock_url}/mock/configure",
        json={"key": model, "responses": responses},
        timeout=5,
        trust_env=False,
    ).raise_for_status()


def _peer_call(call_id: str, target: str, text: str) -> dict[str, Any]:
    return {
        "tool_calls": [
            {
                "call_id": call_id,
                "name": "sys_session_send",
                "arguments": json.dumps({"session_id": target, "args": text}),
            }
        ]
    }


def _user_texts(client: httpx.Client, session_id: str) -> list[str]:
    """Every user-role message text in a session's stored transcript."""
    items = client.get(f"/v1/sessions/{session_id}/items").json().get("data", [])
    texts = []
    for item in items:
        if item.get("type") == "message" and item.get("role") == "user":
            texts.extend(part.get("text", "") for part in item.get("content") or [])
    return texts


def _assistant_text(client: httpx.Client, session_id: str) -> str:
    items = client.get(f"/v1/sessions/{session_id}/items").json().get("data", [])
    return json.dumps([i for i in items if i.get("role") == "assistant"])


def test_two_top_level_sessions_exchange_a_peer_message_and_a_reply(
    tmp_path: Path, mock_model: str
) -> None:
    env = {
        "OPENAI_API_KEY": "mock-key",
        "OPENAI_BASE_URL": f"{mock_model}/v1",
        "OMNIGENT_SKIP_ONBOARD": "1",
        "OMNIGENT_NO_UPDATE_CHECK": "1",
        "OMNIGENT_SKIP_WEB_UI": "true",
    }
    with server_runner(tmp_path / "stack", server_env=env, wait_ready=False) as stack:
        stack.start_runner(env=env)
        with httpx.Client(base_url=stack.base_url, timeout=60.0, trust_env=False) as client:
            sessions = {}
            for name, model in (("alpha", "mock-alpha"), ("beta", "mock-beta")):
                created = post_session_bundle(
                    client.post, "/v1/sessions", _agent_bundle(name, model, mock_model)
                )
                created.raise_for_status()
                sessions[name] = created.json()["session_id"]
                bind_session_runner(client.patch, "", sessions[name], stack.runner_id)
            alpha, beta = sessions["alpha"], sessions["beta"]
            for session_id in (alpha, beta):
                snapshot = client.get(f"/v1/sessions/{session_id}").json()
                # Two unrelated top-level chats of one user: the case a
                # child-only send can never reach.
                assert snapshot["parent_session_id"] is None, snapshot

            # alpha asks beta; when beta's answer lands it takes a turn on it.
            _script(
                mock_model,
                "mock-alpha",
                [
                    _peer_call("peer_ping", beta, _PING),
                    {"text": "Asked the reviewer session."},
                    {"text": "ALPHA_ACK: the reviewer says the review is done."},
                ],
            )
            # beta answers the session named in the envelope it received.
            _script(
                mock_model,
                "mock-beta",
                [_peer_call("peer_pong", alpha, _PONG), {"text": "Answered the asking session."}],
            )

            sent = client.post(
                f"/v1/sessions/{alpha}/events",
                json={
                    "type": "message",
                    "data": {
                        "role": "user",
                        "content": [{"type": "input_text", "text": _KICKOFF}],
                    },
                },
            )
            assert sent.status_code in (200, 202), sent.text

            def healthy() -> None:
                for session_id in (alpha, beta):
                    snapshot = client.get(f"/v1/sessions/{session_id}").json()
                    assert not snapshot.get("last_task_error"), (
                        snapshot["last_task_error"],
                        stack.log_tail(),
                    )

            def received(session_id: str, marker: str) -> str | None:
                healthy()
                return next((t for t in _user_texts(client, session_id) if marker in t), None)

            ping = _wait(lambda: received(beta, _PING), "beta to receive alpha's peer message")
            pong = _wait(lambda: received(alpha, _PONG), "alpha to receive beta's reply")
            # The reply did not just land in the transcript: it started a turn.
            _wait(
                lambda: "ALPHA_ACK" in _assistant_text(client, alpha),
                "alpha to take a turn on the reply",
                60,
            )

            assert ping.startswith(f"[System: peer message from agent 'alpha' in session {alpha}")
            assert pong.startswith(f"[System: peer message from agent 'beta' in session {beta}")
            assert f"session_id='{alpha}'" in ping, "beta needs alpha's address to answer"
            assert pong.count("[System:") == 1, "the reply must not quote the envelope it answers"
            # A peer send must not adopt the target: both stay top-level.
            for session_id in (alpha, beta):
                children = client.get(f"/v1/sessions/{session_id}/child_sessions").json()["data"]
                assert children == [], children
                assert client.get(f"/v1/sessions/{session_id}").json()["parent_session_id"] is None
