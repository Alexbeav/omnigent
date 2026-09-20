"""The generated ACP picker-agent bundle (omnigent/server/app.py).

ACP rows have no provider row and no authored spec: :func:`_build_acp_bundle`
generates a single-``config.yaml`` bundle from a hardcoded template instead.
That makes the template the *only* place these agents get their grants, so a
key missing here is silently absent from every ACP agent at once.

These tests pin the two properties that matter:

- the template grants the session-orchestration writes, so an ACP agent can
  create and drive child sessions like a native agent can; and
- the generated YAML round-trips through the parser to ``spawn=True``, so the
  grant survives the bundle -> spec path rather than only existing in a dict.
"""

from __future__ import annotations

import io
import tarfile
import tempfile
from pathlib import Path

import pytest
import yaml

from omnigent.server.app import _ACP_AGENT_PROMPT, _build_acp_bundle
from omnigent.spec import parser
from omnigent.spec.types import AgentSpec


def _bundle_config_yaml(harness: str, name: str) -> str:
    """Build the ACP bundle and return its generated ``config.yaml`` text.

    :param harness: Harness id to bake into the bundle, e.g. ``"acp:cline"``.
    :param name: Agent name / stable-id seed, e.g. ``"cline"``.
    :returns: The decoded YAML the bundle ships.
    """
    bundle = _build_acp_bundle(harness=harness, name=name)
    with tarfile.open(fileobj=io.BytesIO(bundle)) as tar:
        configs = [n for n in tar.getnames() if n.endswith("config.yaml")]
        assert configs, "ACP bundle must ship a config.yaml"
        member = tar.extractfile(configs[0])
        assert member is not None
        return member.read().decode()


def _parse_bundle_yaml(text: str) -> AgentSpec:
    """Parse generated YAML the way bundle loading does.

    :param text: The ``config.yaml`` contents.
    :returns: The parsed agent spec.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "agent"
        root.mkdir()
        (root / "config.yaml").write_text(text)
        return parser.parse(root)


def test_acp_bundle_grants_spawn() -> None:
    """The ACP template opts into session orchestration.

    Without ``spawn:`` the parser default (False) strips
    ``sys_session_create`` from every ACP agent, leaving them unable to
    delegate to a child session while native agents (polly) can. Guards
    against a future template edit dropping the grant.
    """
    raw = yaml.safe_load(_bundle_config_yaml("acp:cline", "cline"))
    assert raw["spawn"] is True


def test_acp_bundle_spawn_survives_parse() -> None:
    """``spawn`` reaches the parsed spec, not just the generated dict."""
    spec = _parse_bundle_yaml(_bundle_config_yaml("acp:cline", "cline"))
    assert spec.spawn is True


@pytest.mark.parametrize("harness,name", [("acp:cline", "cline"), ("grok", "grok")])
def test_acp_bundle_identity_is_unchanged(harness: str, name: str) -> None:
    """Adding grants must not disturb the rest of the generated template."""
    raw = yaml.safe_load(_bundle_config_yaml(harness, name))
    assert raw["spec_version"] == 1
    assert raw["name"] == name
    assert raw["prompt"] == _ACP_AGENT_PROMPT
    assert raw["executor"] == {"type": "omnigent", "config": {"harness": harness}}
    assert raw["os_env"]["type"] == "caller_process"
