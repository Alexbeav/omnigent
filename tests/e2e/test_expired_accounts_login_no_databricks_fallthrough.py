"""End-to-end repro: an expired accounts login must not fall through to Databricks auth.

In ``accounts`` auth mode a persistent local host (``omnigent host --server
<url>``) bootstraps its runner on the host's current session bearer. When the
stored accounts JWT expires with **no** login-issued refresh material and **no**
Databricks config anywhere on the box, the runner's auth resolution falls
through to the Databricks path: every runner->server callback raises

    httpx.RequestError: Databricks token refresh returned no token

even though Databricks is neither configured nor used, and the operator-facing
remedy log tells them to run ``databricks auth login`` instead of ``omnigent
login``. From the UI this looks like the host/agent stopped working.

This test drives the runner's **real** outbound auth code
(``_InitialAuthTokenFactory`` -> ``_make_auth_token_factory`` ->
``_RunnerDatabricksAuth``) over a **real** socket against a **real** live
``omnigent server`` subprocess in accounts mode. The only thing simulated is the
reported *condition* itself — a persistent host whose stored accounts login has
expired with no refresh material and no Databricks config on disk — which is
exactly what makes the fallthrough fire.

The differential (fail on unfixed ``main`` -> pass once fixed):

* Callback #1 presents the host's now-expired accounts bearer. The live server
  rejects it 401, so the factory invalidates the bearer and tries to resolve a
  local credential — of which there is none.
* Callback #2 (and every subsequent one) must NOT surface a *Databricks*
  token-refresh error for an expired *accounts* login. On unfixed ``main`` it
  raises ``httpx.RequestError("Databricks token refresh returned no token")``;
  the fix must instead let the callback go out bare (cleanly rejected by
  ``require_user``) or stop with a message naming the ``omnigent login`` remedy —
  never the Databricks fallback, since the stored record is a normal accounts
  record, not a Databricks pointer.
* The operator-facing remedy must name ``omnigent login``, never ``databricks
  auth login``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from omnigent.runner._entry import (
    _InitialAuthTokenFactory,
    _RunnerDatabricksAuth,
)
from omnigent.runner.identity import (
    OMNIGENT_INTERNAL_WS_ORIGIN,
    RUNNER_DELEGATED_AUTH_ENV_VAR,
    RUNNER_INITIAL_AUTH_TOKEN_ENV_VAR,
    RUNNER_TUNNEL_BINDING_TOKEN_ENV_VAR,
)
from omnigent.server.oidc import mint_session_token
from tests._helpers.compat import apply_server_env, compat_server_cwd, server_executable
from tests._helpers.live_server import find_free_port
from tests.server.helpers import build_agent_bundle

# Repo root — this file lives at tests/e2e/<name>.py.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# 32-byte cookie secret (64 hex chars), shared between this test process and the
# server subprocess so the accounts bearers we mint validate server-side.
_COOKIE_SECRET_HEX = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2"
_OWNER = "alice@example.com"
_SERVER_HEALTH_TIMEOUT_S = 40.0


def _await_health(base_url: str, log_path: Path) -> None:
    """Poll ``/health`` until the server answers 200, or fail with the log tail.

    :param base_url: Server base URL, e.g. ``"http://localhost:58123"``.
    :param log_path: Server stdout/stderr log, tailed into the failure message.
    :returns: None.
    :raises RuntimeError: If the server doesn't answer within the deadline.
    """
    deadline = time.monotonic() + _SERVER_HEALTH_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{base_url}/health", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            # Expected while the server is still booting (connection refused /
            # reset); keep polling until the deadline.
            pass
        time.sleep(0.5)
    tail = log_path.read_text()[-3000:] if log_path.exists() else "(no log)"
    raise RuntimeError(f"accounts server did not become healthy. Log:\n{tail}")


@pytest.fixture()
def accounts_server(tmp_path: Path) -> Iterator[str]:
    """Run a real ``omnigent server`` subprocess with accounts auth enabled.

    Accounts mode is selected by ``OMNIGENT_AUTH_PROVIDER=accounts`` plus a
    shared cookie secret; the subprocess handles the full runtime lifecycle
    (migrations, DBOS, auth provider, permission store) exactly as a deployed
    server does.

    :param tmp_path: Per-test temp dir for the DB, artifacts, and server log.
    :returns: The running server's base URL.
    """
    port = find_free_port()
    db_path = tmp_path / "e2e.db"
    db_uri = f"sqlite:///{db_path}"
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    log_path = tmp_path / "server.log"
    base_url = f"http://localhost:{port}"

    env = {**os.environ}
    env["OMNIGENT_AUTH_PROVIDER"] = "accounts"
    env["OMNIGENT_ACCOUNTS_COOKIE_SECRET"] = _COOKIE_SECRET_HEX
    env["OMNIGENT_ACCOUNTS_BASE_URL"] = base_url
    # Force the accounts branch of the auth-source switch (an ambient OIDC
    # issuer in the environment would otherwise select oidc mode).
    env.pop("OMNIGENT_OIDC_ISSUER", None)
    # Import the server package from this worktree, not an installed copy.
    apply_server_env(env, _REPO_ROOT)

    log_handle = open(log_path, "w")  # noqa: SIM115 — handle lives for the subprocess
    proc = subprocess.Popen(
        [
            server_executable(),
            "-m",
            "omnigent.cli",
            "server",
            "--port",
            str(port),
            "--database-uri",
            db_uri,
            "--artifact-location",
            str(artifact_dir),
        ],
        env=env,
        cwd=compat_server_cwd(),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    try:
        _await_health(base_url, log_path)
        yield base_url
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        log_handle.close()


def _seed_owned_session(base_url: str) -> str:
    """Create Alice's session so the callback target exists and requires auth.

    Alice's identity comes from a directly-minted (still-valid) accounts cookie
    signed with the server's shared secret — the same JWT the password login
    flow issues; only the password dance is skipped. The session-create and
    agent registration are real, so ``/v1/sessions/<id>/agent/contents`` is a
    real ``require_user`` route (401 without a valid bearer, not 404).

    :param base_url: Live server base URL.
    :returns: The created session id.
    """
    owner_cookie = mint_session_token(
        _OWNER, bytes.fromhex(_COOKIE_SECRET_HEX), 8 * 3600, "accounts"
    )
    bundle = build_agent_bundle(name="e2e-accounts-jwt-expiry-agent")
    with httpx.Client(base_url=base_url, timeout=30.0) as http:
        create = http.post(
            "/v1/sessions",
            headers={
                "Authorization": f"Bearer {owner_cookie}",
                "Origin": OMNIGENT_INTERNAL_WS_ORIGIN,
            },
            data={"metadata": "{}"},
            files={"bundle": ("agent.tar.gz", bundle, "application/gzip")},
        )
    assert create.status_code in (200, 201), (create.status_code, create.text)
    return create.json()["session_id"]


async def _get_agent_contents(
    base_url: str,
    path: str,
    auth: _RunnerDatabricksAuth,
) -> httpx.Response:
    """Drive the runner's real callback client for one ``GET``.

    Builds the same ``httpx.AsyncClient`` the runner uses for its server
    callbacks (``auth=_RunnerDatabricksAuth(...)``, sentinel ``Origin``,
    redirects off) and issues a single request over a real socket.

    :param base_url: Live server base URL.
    :param path: Request path, e.g. ``"/v1/sessions/<id>/agent/contents"``.
    :param auth: The runner's httpx auth wired to the factory under test.
    :returns: The HTTP response.
    """
    async with httpx.AsyncClient(
        base_url=base_url,
        auth=auth,
        headers={"Origin": OMNIGENT_INTERNAL_WS_ORIGIN},
        follow_redirects=False,
        timeout=30.0,
    ) as client:
        return await client.get(path)


def test_expired_accounts_login_does_not_fall_through_to_databricks(
    accounts_server: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A persistent host's expired accounts JWT must not surface a Databricks error.

    Replays the reported failure end-to-end over real sockets. A host-launched runner
    bootstraps on the host's accounts session bearer; that bearer expires and
    the server rejects it; the machine holds no login refresh material and no
    Databricks config. On unfixed ``main`` every subsequent runner->server
    callback raises ``httpx.RequestError("Databricks token refresh returned no
    token")`` and the runner logs the ``databricks auth login`` remedy — both
    wrong for accounts mode. The fix must not select the Databricks fallback
    for a normal (non-pointer) accounts record.

    :param accounts_server: The live accounts-auth server base URL.
    :param monkeypatch: Puts this process into the persistent-host posture
        (injected initial bearer; no managed-sandbox binding token; expired
        accounts login on disk; no Databricks credential resolvable).
    :param caplog: Captures the operator-facing remedy log line.
    :returns: None.
    """
    base_url = accounts_server
    session_id = _seed_owned_session(base_url)
    contents_path = f"/v1/sessions/{session_id}/agent/contents"

    from omnigent.inner.databricks_executor import DatabricksAuthError

    def _no_databricks_creds(*args: object, **kwargs: object) -> tuple[object, str]:
        """Stand in for _resolve_databricks_auth on a host with no Databricks config."""
        raise DatabricksAuthError("this host has no Databricks config")

    # Persistent local host posture (NOT a managed sandbox): the runner holds
    # only the host's injected session bearer — no tunnel binding token and no
    # delegated-mint marker. The stored accounts login has expired with no
    # refresh material, and no Databricks credential resolves anywhere.
    monkeypatch.setenv("RUNNER_SERVER_URL", base_url)
    monkeypatch.delenv(RUNNER_TUNNEL_BINDING_TOKEN_ENV_VAR, raising=False)
    monkeypatch.delenv(RUNNER_DELEGATED_AUTH_ENV_VAR, raising=False)
    monkeypatch.setenv(RUNNER_INITIAL_AUTH_TOKEN_ENV_VAR, "")
    # A normal accounts record whose JWT has lapsed and carries no refresh
    # material — load_token/refresh both come up empty (the reported state).
    monkeypatch.setattr("omnigent.cli_auth.load_token", lambda _url, **_kw: None)
    monkeypatch.setattr("omnigent.cli_auth.refresh_stored_token", lambda _url, **_kw: None)
    monkeypatch.setattr(
        "omnigent.inner.databricks_executor._resolve_databricks_auth",
        _no_databricks_creds,
    )
    # Build a fresh factory (ignore any runner-process singleton).
    import omnigent.runner._entry as entry

    monkeypatch.setattr(entry, "_runner_auth_factory", None, raising=False)

    # The host's accounts session bearer, already expired — exactly what a
    # long-running host is left holding once its stored JWT lapses.
    expired_host_bearer = mint_session_token(
        _OWNER, bytes.fromhex(_COOKIE_SECRET_HEX), -3600, "accounts"
    )
    factory = _InitialAuthTokenFactory(expired_host_bearer, base_url)

    with caplog.at_level(logging.INFO):
        # Callback #1: the injected bearer is presented and the live server
        # rejects it (401), so the factory invalidates it and tries to resolve
        # a local credential — of which there is none.
        first = asyncio.run(
            _get_agent_contents(base_url, contents_path, _RunnerDatabricksAuth(factory))
        )
        assert first.status_code in (401, 403), (first.status_code, first.text)

        # Callback #2: with the bearer invalidated and no local credential, the
        # runner must not fall through to the Databricks path.
        raised: httpx.RequestError | None = None
        second: httpx.Response | None = None
        try:
            second = asyncio.run(
                _get_agent_contents(base_url, contents_path, _RunnerDatabricksAuth(factory))
            )
        except httpx.RequestError as exc:
            raised = exc

    # (1) No Databricks fallthrough. On unfixed main callback #2 raises
    #     httpx.RequestError("Databricks token refresh returned no token").
    if raised is not None:
        message = str(raised)
        assert "databricks" not in message.lower(), (
            "expired accounts JWT fell through to the Databricks auth path: " f"{message!r}"
        )
        # If it does stop the callback, it must name the Omnigent login remedy.
        assert "omnigent login" in message.lower(), (
            "callback stopped without naming the omnigent login remedy: " f"{message!r}"
        )
    else:
        # Went out bare: require_user cleanly rejects it (not a Databricks crash).
        assert second is not None
        assert second.status_code in (401, 403), (second.status_code, second.text)

    # (2) The operator-facing remedy must name `omnigent login`, never point an
    #     accounts-mode host at `databricks auth login`.
    remedy_logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "databricks auth login" not in remedy_logs.lower(), (
        "remedy log points an accounts-mode host at Databricks:\n" f"{remedy_logs}"
    )
