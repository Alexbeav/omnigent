"""Portable failure coverage for owned Windows Job Object handles."""

from __future__ import annotations

import threading
from unittest.mock import Mock

import pytest

from omnigent.inner import windows_jobobject_sandbox as jobobject


def test_failed_close_retains_job_handle_for_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = Mock()
    kernel.CloseHandle.side_effect = [0, 1]
    monkeypatch.setattr(jobobject, "_kernel32", lambda: kernel)
    monkeypatch.setattr(jobobject, "_get_last_error", lambda: 5)
    job = jobobject._JobHandle(42)
    with pytest.raises(OSError, match="retry cleanup") as caught:
        job.close()
    assert caught.value.errno == 5
    assert job._handle == 42
    job.close()
    job.close()
    assert job._handle is None
    assert [call.args[0].value for call in kernel.CloseHandle.call_args_list] == [42, 42]


def test_concurrent_close_releases_job_once(monkeypatch: pytest.MonkeyPatch) -> None:
    entered, release = threading.Event(), threading.Event()

    def close(_handle: object) -> int:
        entered.set()
        assert release.wait(1)
        return 1

    kernel = Mock()
    kernel.CloseHandle.side_effect = close
    monkeypatch.setattr(jobobject, "_kernel32", lambda: kernel)
    job = jobobject._JobHandle(42)
    first = threading.Thread(target=job.close)
    second = threading.Thread(target=job.close)
    first.start()
    try:
        assert entered.wait(1)
        second.start()
    finally:
        release.set()
        first.join(1)
        if second.ident is not None:
            second.join(1)
    assert not first.is_alive() and not second.is_alive()
    kernel.CloseHandle.assert_called_once()
    assert job._handle is None
