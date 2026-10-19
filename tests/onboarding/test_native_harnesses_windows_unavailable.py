"""Windows harness-readiness regressions."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import omnigent.onboarding.harness_install as hi
import omnigent.onboarding.harness_readiness as readiness
from omnigent.harness_aliases import NATIVE_HARNESSES


@pytest.fixture(autouse=True)
def _isolate_credentials(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OMNIGENT_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("OMNIGENT_WINDOWS_NATIVE_TERMINALS", raising=False)
    monkeypatch.delenv("OMNIGENT_WINDOWS_NATIVE_HARNESSES", raising=False)
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    for var in ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.delenv(var, raising=False)

    import omnigent.onboarding.copilot_auth as _ca

    monkeypatch.setattr(_ca, "gh_cli_github_token", lambda host=None: None)

    import omnigent._platform as _plat

    monkeypatch.delenv("OMNIGENT_CODEX_PATH", raising=False)
    monkeypatch.setattr(_plat, "_cli_fallback_dirs", lambda: ())


def _all_clis_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hi.shutil, "which", lambda name: f"/usr/bin/{name}")

    def _stub_run(argv: list[str], **k: object) -> subprocess.CompletedProcess[str]:
        if len(argv) >= 2 and argv[1] == "--version":
            if argv[0].endswith("opencode"):
                version = "1.17.7\n"
            elif argv[0].endswith("cursor-agent") or argv[0].endswith("hermes"):
                version = "2026.07.01\n"
            else:
                version = "9.9.9\n"
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=version, stderr="")
        if argv[:3] == ["gh", "auth", "token"]:
            return subprocess.CompletedProcess(args=argv, returncode=1, stdout="", stderr="")
        raise AssertionError(f"unexpected subprocess in readiness tests: {argv!r}")

    monkeypatch.setattr(hi.subprocess, "run", _stub_run)
    monkeypatch.setattr(hi, "harness_cli_logged_in", lambda _key, **_kw: True)


@pytest.mark.parametrize("harness", sorted(NATIVE_HARNESSES))
def test_native_terminal_harness_unavailable_on_windows(
    monkeypatch: pytest.MonkeyPatch,
    harness: str,
) -> None:
    _all_clis_installed(monkeypatch)
    import omnigent._platform as _plat

    monkeypatch.setattr(_plat, "IS_WINDOWS", True)
    monkeypatch.setattr(readiness, "IS_WINDOWS", True)

    result = readiness.configured_harness_map()

    assert result.get(harness) == "unsupported-platform"
    assert readiness.harness_is_configured(harness) is False


def test_sdk_harnesses_remain_available_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _all_clis_installed(monkeypatch)
    import omnigent._platform as _plat

    monkeypatch.setattr(_plat, "IS_WINDOWS", True)
    monkeypatch.setattr(readiness, "IS_WINDOWS", True)
    # SDK readiness is credential-based (True only when a locally visible
    # credential source could serve the harness, else "needs-auth"), so give
    # each family an ambient key: this test asserts the *Windows gate* never
    # knocks the in-process SDK harnesses out, not that they are ready on a
    # credential-less host.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-windows-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-windows-test")

    result = readiness.configured_harness_map()

    for sdk_harness in ("claude-sdk", "claude_sdk", "openai-agents", "openai-agents-sdk"):
        assert result.get(sdk_harness) is True


@pytest.mark.parametrize(
    "selection, expected",
    [
        ("codex-native", {"codex-native", "native-codex"}),
        ("claude-native", {"claude-native", "native-claude"}),
        (
            "native-codex, claude-native, pi-native",
            {"codex-native", "native-codex", "claude-native", "native-claude"},
        ),
    ],
)
def test_windows_pilot_exposes_only_selected_core_harnesses(
    monkeypatch: pytest.MonkeyPatch, selection: str, expected: set[str]
) -> None:
    _all_clis_installed(monkeypatch)
    monkeypatch.setattr(readiness, "IS_WINDOWS", True)
    monkeypatch.setattr(readiness, "_windows_native_dependencies_available", lambda: True)
    monkeypatch.setattr(
        "omnigent.harnesses.codex_native.main._codex_auth_unavailable_reason", lambda: None
    )
    monkeypatch.setenv("OMNIGENT_WINDOWS_NATIVE_TERMINALS", "1")
    monkeypatch.setenv("OMNIGENT_WINDOWS_NATIVE_HARNESSES", selection)
    result = readiness.configured_harness_map()
    for harness in NATIVE_HARNESSES:
        assert result[harness] == (True if harness in expected else "unsupported-platform")
        assert readiness.harness_is_configured(harness) is (harness in expected)


@pytest.mark.parametrize("transport, dependencies", [("", True), ("1", False)])
def test_windows_pilot_requires_transport_and_its_runtime(
    monkeypatch: pytest.MonkeyPatch, transport: str, dependencies: bool
) -> None:
    _all_clis_installed(monkeypatch)
    monkeypatch.setattr(readiness, "IS_WINDOWS", True)
    monkeypatch.setattr(readiness, "_windows_native_dependencies_available", lambda: dependencies)
    monkeypatch.setenv("OMNIGENT_WINDOWS_NATIVE_TERMINALS", transport)
    monkeypatch.setenv("OMNIGENT_WINDOWS_NATIVE_HARNESSES", "codex-native,claude-native")
    for harness in ("codex-native", "claude-native"):
        assert readiness._harness_availability(harness) == "unsupported-platform"
        assert not readiness.harness_is_configured(harness)


@pytest.mark.parametrize("reason", ["binary-missing", "version-too-low", "needs-auth"])
@pytest.mark.parametrize("harness", ["codex-native", "native-codex"])
def test_windows_pilot_preserves_selected_codex_readiness_failures(
    monkeypatch: pytest.MonkeyPatch, reason: str, harness: str
) -> None:
    monkeypatch.setattr(readiness, "IS_WINDOWS", True)
    monkeypatch.setattr(readiness, "_windows_native_dependencies_available", lambda: True)
    monkeypatch.setattr(
        "omnigent.harnesses.codex_native.main._codex_auth_unavailable_reason", lambda: reason
    )
    monkeypatch.setenv("OMNIGENT_WINDOWS_NATIVE_TERMINALS", "1")
    monkeypatch.setenv("OMNIGENT_WINDOWS_NATIVE_HARNESSES", "codex-native")
    assert readiness._harness_availability(harness) == reason
    assert readiness._harness_availability_core(harness) == reason
    assert not readiness.harness_is_configured(harness)
