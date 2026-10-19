"""Native executable selection with local npm fixtures; no CLI is executed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from omnigent import _platform
from omnigent.native import codex_binary


@pytest.fixture(autouse=True)
def _isolate_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_platform, "IS_WINDOWS", True)
    monkeypatch.setattr(_platform, "_cli_fallback_dirs", lambda: ())
    monkeypatch.delenv("OMNIGENT_CODEX_PATH", raising=False)
    monkeypatch.setattr(codex_binary.platform, "machine", lambda: "AMD64")


def _npm_install(
    tmp_path: Path, *, local: bool = False, arch: str = "x64"
) -> tuple[Path, Path, Path]:
    modules = tmp_path / "node_modules"
    root = modules / "@openai" / "codex"
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "codex.js").write_text("// fixture\n", encoding="utf-8")
    dependency = f"@openai/codex-win32-{arch}"
    version = f"0.139.0-win32-{arch}"
    (root / "package.json").write_text(
        json.dumps(
            {
                "name": "@openai/codex",
                "version": "0.139.0",
                "bin": {"codex": "bin/codex.js"},
                "optionalDependencies": {dependency: f"npm:@openai/codex@{version}"},
            }
        ),
        encoding="utf-8",
    )
    package = root / "node_modules" / dependency
    package.mkdir(parents=True)
    (package / "package.json").write_text(
        json.dumps(
            {
                "name": "@openai/codex",
                "version": version,
                "os": ["win32"],
                "cpu": [arch],
            }
        ),
        encoding="utf-8",
    )
    triple = "x86_64" if arch == "x64" else "aarch64"
    exe = package / "vendor" / f"{triple}-pc-windows-msvc" / "bin" / "codex.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"fixture: never execute")
    exe.chmod(0o755)
    shim = (modules / ".bin" if local else tmp_path) / "codex.cmd"
    shim.parent.mkdir(parents=True, exist_ok=True)
    relative = ".." if local else "node_modules"
    shim.write_text(
        f'@node "%dp0%\\{relative}\\@openai\\codex\\bin\\codex.js" %*\n', encoding="utf-8"
    )
    return shim, root, exe


@pytest.mark.parametrize("local", [False, True])
@pytest.mark.parametrize(
    "machine, arch", [("AMD64", "x64"), ("x86_64", "x64"), ("ARM64", "arm64")]
)
def test_windows_resolves_same_package_npm_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, local: bool, machine: str, arch: str
) -> None:
    shim, _, exe = _npm_install(tmp_path / "Ελληνικά with spaces", local=local, arch=arch)
    monkeypatch.setattr(codex_binary.platform, "machine", lambda: machine)

    def lookup(name: str) -> str | None:
        return str(shim) if name == "codex" else None

    assert _platform.resolve_cli_binary("codex", which=lookup) == str(shim)
    assert codex_binary.resolve_native_codex_binary(which=lookup) == str(exe)


def test_windows_prefers_real_executable_over_shim(tmp_path: Path) -> None:
    shim, _, exe = _npm_install(tmp_path)
    assert codex_binary.resolve_native_codex_binary(
        which=lambda name: str(exe) if name == "codex.exe" else str(shim)
    ) == str(exe)


@pytest.mark.parametrize("layout", ["hoisted", "bundled"])
def test_windows_recognizes_package_local_vendor_layouts(tmp_path: Path, layout: str) -> None:
    shim, root, exe = _npm_install(tmp_path)
    package = exe.parents[3]
    if layout == "hoisted":
        moved = root.parent / "codex-win32-x64"
        package.rename(moved)
        expected = moved / exe.relative_to(package)
    else:
        expected = root / exe.relative_to(package)
        (package / "vendor").rename(root / "vendor")
        (package / "package.json").unlink()
        package.rmdir()
    assert codex_binary.resolve_native_codex_binary(
        which=lambda name: str(shim) if name == "codex" else None
    ) == str(expected)


def test_windows_refuses_payload_symlink_outside_the_package(tmp_path: Path) -> None:
    shim, _, exe = _npm_install(tmp_path)
    outside = tmp_path / "unrelated.exe"
    exe.rename(outside)
    exe.symlink_to(outside)
    assert (
        codex_binary.resolve_native_codex_binary(
            which=lambda name: str(shim) if name == "codex" else None
        )
        is None
    )


@pytest.mark.parametrize("override", ["missing.exe", "codex.cmd", "named-custom"])
def test_windows_override_never_switches_to_another_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, override: str
) -> None:
    shim, _, exe = _npm_install(tmp_path)
    selected = str(shim) if override == "codex.cmd" else override
    monkeypatch.setenv("OMNIGENT_CODEX_PATH", selected)
    seen = []

    def lookup(name: str) -> str | None:
        seen.append(name)
        return str(exe) if name in {"codex", "codex.exe"} else None

    assert codex_binary.resolve_native_codex_binary(which=lookup) is None
    assert seen == [selected]


@pytest.mark.parametrize("named", [False, True])
def test_windows_executable_override_wins_even_with_different_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, named: bool
) -> None:
    _, _, exe = _npm_install(tmp_path)
    custom = tmp_path / "configured.EXE"
    custom.write_bytes(b"configured fixture")
    custom.chmod(0o755)
    monkeypatch.setenv("OMNIGENT_CODEX_PATH", "configured" if named else str(custom))
    assert codex_binary.resolve_native_codex_binary(
        which=lambda name: (
            str(custom) if name == "configured" else str(exe) if name == "codex" else None
        )
    ) == str(custom)


@pytest.mark.parametrize(
    "field, value",
    [
        ("name", "other"),
        ("version", "wrong-version"),
        ("os", ["linux"]),
        ("cpu", ["arm64"]),
        ("cpu", None),
    ],
)
def test_wrong_platform_or_dependency_identity_is_refused(
    tmp_path: Path, field: str, value: object
) -> None:
    shim, _, exe = _npm_install(tmp_path)
    manifest = exe.parents[3] / "package.json"
    package = json.loads(manifest.read_text(encoding="utf-8"))
    package[field] = value
    manifest.write_text(json.dumps(package), encoding="utf-8")
    assert (
        codex_binary.resolve_native_codex_binary(
            which=lambda name: str(shim) if name == "codex" else None
        )
        is None
    )


@pytest.mark.parametrize(
    "fault",
    [
        "no-exe",
        "no-manifest",
        "malformed",
        "wrong-parent",
        "wrong-bin",
        "unrelated-shim",
        "unknown-arch",
        "ambiguous",
    ],
)
def test_absent_unverified_or_ambiguous_payload_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    shim, root, exe = _npm_install(tmp_path)
    if fault == "no-exe":
        exe.unlink()
    elif fault == "no-manifest":
        (exe.parents[3] / "package.json").unlink()
    elif fault == "malformed":
        (root / "package.json").write_text("{", encoding="utf-8")
    elif fault in {"wrong-parent", "wrong-bin"}:
        manifest = root / "package.json"
        package = json.loads(manifest.read_text(encoding="utf-8"))
        package["name" if fault == "wrong-parent" else "bin"] = "unrelated"
        manifest.write_text(json.dumps(package), encoding="utf-8")
    elif fault == "unrelated-shim":
        shim.write_text("@node other.js", encoding="utf-8")
    elif fault == "unknown-arch":
        monkeypatch.setattr(codex_binary.platform, "machine", lambda: "unsupported")
    elif fault == "ambiguous":
        bundled = root / "vendor" / "x86_64-pc-windows-msvc" / "bin" / "codex.exe"
        bundled.parent.mkdir(parents=True)
        bundled.write_bytes(b"different fixture")
        bundled.chmod(0o755)
    assert (
        codex_binary.resolve_native_codex_binary(
            which=lambda name: str(shim) if name == "codex" else None
        )
        is None
    )


def test_posix_delegates_override_and_fallback_behavior_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_platform, "IS_WINDOWS", False)
    monkeypatch.setenv("OMNIGENT_CODEX_PATH", "configured")

    def lookup(name: str) -> str | None:
        return "/configured/codex" if name == "configured" else None

    assert codex_binary.resolve_native_codex_binary(which=lookup) == "/configured/codex"


def test_posix_keeps_script_clis_and_invalid_override_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_platform, "IS_WINDOWS", False)
    monkeypatch.setenv("OMNIGENT_CODEX_PATH", str(tmp_path / "missing"))
    assert (
        codex_binary.resolve_native_codex_binary(
            which=lambda name: "/installed/codex.cmd" if name == "codex" else None
        )
        == "/installed/codex.cmd"
    )
