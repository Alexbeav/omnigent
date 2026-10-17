"""Native Windows process probe, also runnable without pytest's POSIX setup.

Run ``python -m tests.terminals.conpty_probe --root <new-owned-directory>`` in
an isolated candidate with the windows-native extra. No provider is started.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import psutil

from omnigent.terminals import conpty


def run_probe(root_dir: Path, *, capture_screen: bool = False) -> dict[str, object]:
    """Exercise the real binding and fail if owned processes do not drain."""
    if not conpty.IS_WINDOWS or not __debug__:
        raise RuntimeError("The probe requires native Windows with assertions enabled.")
    cwd = root_dir / "Ελληνικά with spaces"
    cwd.mkdir(parents=True, exist_ok=False)
    (cwd / "fixture.txt").write_text("owned fixture", encoding="utf-8")
    fixture = cwd / "terminal fixture.py"
    fixture.write_text(
        "import json, os, pathlib, subprocess, sys\n"
        "print('FIXTURE_READY', flush=True)\n"
        "for line in sys.stdin:\n"
        "    value = json.loads(line)\n"
        "    if value['op'] == 'exit':\n"
        "        print('FIXTURE_FINAL', flush=True)\n"
        "        sys.exit(7)\n"
        "    if value['op'] == 'child':\n"
        "        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(90)'])\n"
        "        pathlib.Path('child.pid').write_text(str(child.pid))\n"
        "    print('FIXTURE_REPLY:' + json.dumps({'text': value['text'], 'cwd': os.getcwd(),\n"
        "        'file': pathlib.Path('fixture.txt').read_text()}, ensure_ascii=False),\n"
        "        flush=True)\n",
        encoding="utf-8",
    )

    def receive(viewer: conpty.OutputSubscription, expected: str) -> str:
        output = ""
        deadline = time.monotonic() + 15
        while expected not in output:
            remaining = deadline - time.monotonic()
            assert remaining > 0, "ConPTY fixture marker deadline expired."
            item = viewer.read(timeout=min(5, remaining))
            assert item is not None, "ConPTY exited before the expected fixture marker."
            output += item
            assert len(output) <= 1024 * 1024, "Unexpected fixture output volume."
        return output

    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        in {
            "SYSTEMROOT",
            "WINDIR",
            "PATH",
            "PATHEXT",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "HOMEDRIVE",
            "HOMEPATH",
            "APPDATA",
            "LOCALAPPDATA",
        }
    }
    environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    session = conpty.spawn_conpty(
        [sys.executable, "-u", str(fixture)],
        cwd=cwd,
        env=environment,
        cols=500,
        capture_screen=capture_screen,
    )
    process = psutil.Process(session.pid)
    process_birth = process.create_time()
    descendant = None
    try:
        viewer = session.subscribe()
        receive(viewer, "FIXTURE_READY")
        session.resize(36, 500).result(timeout=5)
        for index, op in enumerate(("message", "child")):
            if index:
                session.unsubscribe(viewer)
                viewer = session.subscribe(replay=False)
            text = f"Καλημέρα 😀 {index}\nsecond line & literal |"
            session.write(json.dumps({"op": op, "text": text}, ensure_ascii=False) + "\r").result(
                timeout=5
            )
            expected = "FIXTURE_REPLY:" + json.dumps(
                {"text": text, "cwd": str(cwd), "file": "owned fixture"}, ensure_ascii=False
            )
            receive(viewer, expected)
            assert process.is_running() and process.create_time() == process_birth
        descendant = psutil.Process(int((cwd / "child.pid").read_text()))
        descendant_birth = descendant.create_time()
        session.write('{"op":"exit"}\r').result(timeout=5)
        receive(viewer, "FIXTURE_FINAL")
        deadline = time.monotonic() + 15
        while viewer.read(timeout=5) is not None:
            assert time.monotonic() < deadline, "ConPTY EOF deadline expired."
        assert session.exit_status == 7
        if capture_screen:
            captured = session.capture(100)
            assert "FIXTURE_FINAL" in captured.text
            assert "FIXTURE_REPLY:" in captured.text and "Καλημέρα" in captured.text
    finally:
        session.close()
    assert not session.workers_alive
    assert not process.is_running()
    assert descendant is not None
    descendant.wait(timeout=5)
    assert not descendant.is_running()
    return {
        "status": "passed",
        "two_turns": True,
        "unicode_cwd_and_file": True,
        "multiline_unicode_input": True,
        "reconnect_preserved_process": True,
        "resize_completed": True,
        "exit_status": session.exit_status,
        "child_pid": process.pid,
        "child_birth": process_birth,
        "descendant_pid": descendant.pid,
        "descendant_birth": descendant_birth,
        "owned_processes_remaining": 0,
        "io_workers_remaining": 0,
        "rendered_capture": capture_screen,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--capture-screen", action="store_true")
    arguments = parser.parse_args()
    print(json.dumps(run_probe(arguments.root, capture_screen=arguments.capture_screen), indent=2))
