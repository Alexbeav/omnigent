"""Resolve a directly launchable Codex without executing npm shell shims."""

from __future__ import annotations

import json
import os
import platform
from collections.abc import Callable
from pathlib import Path

from omnigent import _platform

_OVERRIDE = "OMNIGENT_CODEX_PATH"
_WINDOWS_TARGETS = {
    "amd64": ("x64", "x86_64-pc-windows-msvc"),
    "x86_64": ("x64", "x86_64-pc-windows-msvc"),
    "arm64": ("arm64", "aarch64-pc-windows-msvc"),
    "aarch64": ("arm64", "aarch64-pc-windows-msvc"),
}


def resolve_native_codex_binary(*, which: Callable[[str], str | None] | None = None) -> str | None:
    """Keep POSIX lookup; on Windows select an exe or a verified npm payload.

    An explicit Windows override must itself resolve to an executable. It is
    never replaced with a package payload or a different binary from PATH.
    """
    which = _platform.shutil.which if which is None else which
    if not _platform.IS_WINDOWS:
        return _platform.resolve_cli_binary("codex", env_var=_OVERRIDE, which=which)
    override = os.environ.get(_OVERRIDE, "").strip()
    if override:
        return _executable(which(override) or override)
    direct = which("codex.exe")
    if direct is not None:
        return _executable(direct)
    selected = _platform.resolve_cli_binary("codex", which=which)
    if selected is None:
        return None
    direct = _executable(selected)
    if direct is not None:
        return direct
    try:
        return _npm_payload(Path(selected))
    except (OSError, ValueError, UnicodeError):
        return None


def _executable(path: str) -> str | None:
    candidate = Path(path)
    if (
        candidate.suffix.lower() == ".exe"
        and candidate.is_file()
        and os.access(candidate, os.X_OK)
    ):
        return str(candidate)
    return None


def _manifest(root: Path) -> dict[str, object]:
    with (root / "package.json").open("rb") as source:
        body = source.read(65_537)
    if len(body) > 65_536:
        return {}
    value = json.loads(body)
    return value if isinstance(value, dict) else {}


def _npm_payload(shim: Path) -> str | None:
    target = _WINDOWS_TARGETS.get(platform.machine().lower())
    if target is None or shim.suffix.lower() not in {".cmd", ".bat"}:
        return None
    with shim.open("rb") as source:
        body = source.read(65_537)
    if len(body) > 65_536:
        return None
    script = body.decode("utf-8-sig").replace("/", "\\").lower()
    # npm global-prefix and node_modules/.bin layouts, respectively.
    layouts = (
        (
            shim.parent / "node_modules" / "@openai" / "codex",
            "node_modules\\@openai\\codex\\bin\\codex.js",
        ),
        (shim.parent.parent / "@openai" / "codex", "..\\@openai\\codex\\bin\\codex.js"),
    )
    roots = []
    for root, relative in layouts:
        if not any(f'"{prefix}\\{relative}"' in script for prefix in ("%dp0%", "%~dp0")):
            continue
        metadata = _manifest(root)
        bins = metadata.get("bin")
        if (
            metadata.get("name") == "@openai/codex"
            and isinstance(metadata.get("version"), str)
            and isinstance(bins, dict)
            and bins.get("codex") in ("bin/codex.js", "./bin/codex.js")
            and (root / "bin" / "codex.js").is_file()
        ):
            roots.append((root, metadata))
    if len(roots) != 1:
        return None
    root, metadata = roots[0]
    arch, triple = target
    relative_exe = Path("vendor") / triple / "bin" / "codex.exe"
    candidates = []
    bundled = root / relative_exe
    if bundled.is_file():
        candidates.append((root, bundled))
    dependency = f"@openai/codex-win32-{arch}"
    optional = metadata.get("optionalDependencies")
    if isinstance(optional, dict) and dependency in optional:
        for directory in (root / "node_modules" / dependency, root.parent / f"codex-win32-{arch}"):
            if not directory.exists():
                continue
            package = _manifest(directory)
            version = package.get("version")
            if (
                package.get("name") != "@openai/codex"
                or not isinstance(version, str)
                or optional[dependency] != f"npm:@openai/codex@{version}"
                or package.get("os") != ["win32"]
                or package.get("cpu") != [arch]
            ):
                return None
            candidates.append((directory, directory / relative_exe))
    resolved = set()
    for directory, candidate in candidates:
        real = candidate.resolve()
        # The payload must remain inside this installation, including symlinks.
        if not real.is_relative_to(directory.resolve()) or _executable(str(real)) is None:
            return None
        resolved.add(str(real))
    return resolved.pop() if len(resolved) == 1 else None
