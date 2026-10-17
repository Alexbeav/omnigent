"""Check an isolated source toolchain without installing or repairing anything."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILES = ("portable-checks", "windows-conpty")


def command(argv: list[str], root: Path, *, timeout: float = 5) -> str | None:
    """Return successful output; discard failure output that may contain secrets."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    try:
        process = subprocess.Popen(
            argv,
            cwd=root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=os.name != "nt",
        )
    except OSError:
        return None
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            # Windows probes run only this interpreter, without spawning children.
            process.kill()
        else:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        return None
    return output.strip() if process.returncode == 0 else None


def check(root: Path, profile: str) -> dict[str, object]:
    """Qualify executable dependencies against this checkout's locked versions."""
    checks: list[dict[str, object]] = []

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    record("python", sys.version_info[:2] == (3, 12), platform.python_version())
    compatible = os.name == "nt" if profile == "windows-conpty" else os.name != "nt"
    record("platform", compatible, platform.system() + "/" + platform.machine())
    try:
        lock_bytes = (root / "uv.lock").read_bytes()
        lock = tomllib.loads(lock_bytes.decode("utf-8"))
        packages: dict[str, set[str]] = {}
        for package in lock["package"]:
            packages.setdefault(package["name"], set()).add(package["version"])
    except (OSError, ValueError, KeyError, TypeError):
        record("uv.lock", False, "Missing or invalid source lockfile")
        return {"profile": profile, "passed": False, "checks": checks}

    git = shutil.which("git")
    head = command([git, "rev-parse", "--verify", "HEAD"], root) if git else None
    top = command([git, "rev-parse", "--show-toplevel"], root) if git else None
    baseline = command([git, "cat-file", "-e", "HEAD:uv.lock"], root) if git and head else None
    valid_git = bool(head and top and Path(top).resolve() == root and baseline is not None)
    record(
        "git-baseline",
        valid_git,
        head if valid_git and head else "A source checkout with a committed uv.lock is required",
    )

    for module, directory in (
        ("omnigent", root / "omnigent"),
        ("omnigent_client", root / "sdks/python-client/omnigent_client"),
        ("omnigent_ui_sdk", root / "sdks/ui/omnigent_ui_sdk"),
    ):
        spec = importlib.util.find_spec(module)
        origin = Path(spec.origin).resolve() if spec and spec.origin else None
        record(
            module,
            origin == directory / "__init__.py",
            "Source import resolves to this checkout"
            if origin == directory / "__init__.py"
            else "Source import resolves elsewhere or is missing",
        )

    modules = (
        {"pytest": "pytest", "ruff": "ruff", "pyrefly": "pyrefly", "pre-commit": "pre_commit"}
        if profile == "portable-checks"
        else {"pywinpty": "winpty", "pyte": "pyte"}
    )
    for distribution, module in modules.items():
        expected = packages.get(distribution, set())
        try:
            installed = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            installed = "missing"
        pinned = len(expected) == 1 and installed in expected
        record(
            distribution + "-version",
            pinned,
            "Installed " + installed + "; locked " + ", ".join(sorted(expected)),
        )
        if not compatible:
            continue
        if profile == "portable-checks":
            output = command([sys.executable, "-m", module, "--version"], root)
            executable = output is not None and installed in output.split()
        else:
            output = command([sys.executable, "-c", "import " + module], root)
            executable = output is not None
        record(
            distribution + "-executable",
            executable,
            "Executable/import probe passed"
            if executable
            else "Executable/import probe failed; package metadata alone is insufficient",
        )

    if profile == "portable-checks" and compatible:
        node = shutil.which("node")
        version = command([node, "--version"], root) if node else None
        record(
            "node",
            bool(version and version.startswith("v24.")),
            version
            if version and version.startswith("v24.")
            else "Node 24.x is required for this development profile",
        )
        probe = (
            "const r=require('node:module').createRequire("
            "require('node:path').resolve('web/package.json'));"
            "const t=r('typescript');if(typeof t.createProgram!=='function')process.exit(1);"
            "process.stdout.write(t.version)"
        )
        typescript = command([node, "-e", probe], root) if node else None
        record(
            "typescript",
            typescript is not None and bool(typescript),
            "Compiler resolves from web/package.json"
            if typescript
            else "TypeScript compiler is missing from the source frontend dependency tree",
        )

    return {
        "schema_version": 1,
        "profile": profile,
        "passed": all(item["passed"] for item in checks),
        "source_commit": head,
        "uv_lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--profile", choices=PROFILES, default="portable-checks")
    args = parser.parse_args(argv)
    result = check(args.root.resolve(), args.profile)
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
