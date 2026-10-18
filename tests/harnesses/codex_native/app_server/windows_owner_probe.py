"""Real Windows process ownership with a Python fixture; no Codex or provider."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import psutil


def run_probe(root: Path) -> dict[str, object]:
    if os.name != "nt":
        raise RuntimeError("This ownership probe requires native Windows")
    root.mkdir(parents=True, exist_ok=False)
    source_home, workspace = root / "source-home", root / "workspace"
    source_home.mkdir()
    workspace.mkdir()
    leaf = (
        "import json,pathlib,psutil,time; p=psutil.Process(); "
        "pathlib.Path('leaf.tmp').write_text(json.dumps({'pid':p.pid,'birth':p.create_time()})); "
        "pathlib.Path('leaf.tmp').replace('owned-leaf.json'); time.sleep(60)"
    )
    # Python receives `app-server` as its script path instead of starting Codex.
    (workspace / "app-server").write_text(
        "import ctypes,json,pathlib,subprocess,sys,time,psutil\n"
        f"child=subprocess.Popen([sys.executable,'-c',{leaf!r}],\n"
        " creationflags=subprocess.CREATE_NO_WINDOW)\n"
        "p=psutil.Process(child.pid)\n"
        "pathlib.Path('child.tmp').write_text(json.dumps(\n"
        " {'pid':p.pid,'birth':p.create_time(),\n"
        "  'console_window':int(ctypes.windll.kernel32.GetConsoleWindow())}))\n"
        "pathlib.Path('child.tmp').replace('owned-child.json')\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )

    async def exercise() -> dict[str, object]:
        # Import only after selecting the private source home below.
        from omnigent.harnesses.codex_native.app_server import CodexNativeAppServer

        class Client:
            async def close(self) -> None:
                pass

        async def version(_path: str) -> tuple[int, int, int]:
            return (0, 147, 0)

        async def ready(server: CodexNativeAppServer) -> Client:
            deadline = asyncio.get_running_loop().time() + 10
            while not all(
                (workspace / name).exists() for name in ("owned-child.json", "owned-leaf.json")
            ):
                assert server.proc is not None and server.proc.returncode is None
                assert asyncio.get_running_loop().time() < deadline, "Fixture did not start"
                await asyncio.sleep(0.02)
            assert server._windows_process_owner is not None
            return Client()

        async def trust(_server: CodexNativeAppServer, **_kwargs: object) -> None:
            pass

        server = CodexNativeAppServer(
            codex_path=sys.executable,
            socket_path=root / "unused.sock",
            codex_home=root / "session-home",
            env=dict(os.environ),
            config_overrides=[],
            cwd=workspace,
            bridge_dir=root / "bridge",
            python_executable=sys.executable,
            listen_url="ws://127.0.0.1:1",
            reconcile_process_registry=False,
        )
        with (
            patch("omnigent.harnesses.codex_native.app_server._codex_cli_version", version),
            patch.object(CodexNativeAppServer, "_wait_until_ready", ready),
            patch.object(CodexNativeAppServer, "_trust_policy_hooks", trust),
        ):
            try:
                await server.start()
                assert server.proc is not None
                parent = psutil.Process(server.proc.pid)
                child_record = json.loads((workspace / "owned-child.json").read_text())
                assert psutil.Process(child_record["pid"]).create_time() == child_record["birth"]
                assert child_record["console_window"] == 0
                leaf_record = json.loads((workspace / "owned-leaf.json").read_text())
                child = psutil.Process(leaf_record["pid"])
                assert child.create_time() == leaf_record["birth"]
                # A Windows venv launcher can insert a second Python process.
                ancestry = child.parents()
                assert parent.pid in {p.pid for p in ancestry}
                owned = [
                    child,
                    *ancestry[
                        : next(i for i, p in enumerate(ancestry) if p.pid == parent.pid) + 1
                    ],
                ]
                assert child_record["pid"] in {p.pid for p in owned}
                records = [{"pid": p.pid, "birth": p.create_time()} for p in owned]
            finally:
                await server.close()
        _, alive = psutil.wait_procs(owned, timeout=5)
        assert not alive, "Owned fixture processes survived app-server close"
        assert server.proc is None and server._windows_process_owner is None
        return {
            "status": "passed",
            "processes": records,
            "owned_processes_remaining": 0,
            "real_windows_job_object": True,
            "fixture_only": True,
            "hidden_console": True,
            "provider_started": False,
            "readiness_and_hook_rpc": "fixture stubs; no provider qualification",
        }

    with patch.dict(os.environ, {"CODEX_HOME": str(source_home)}):
        return asyncio.run(exercise())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    print(json.dumps(run_probe(parser.parse_args().root)))
