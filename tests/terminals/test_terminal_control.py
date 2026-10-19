"""Portable transport faults use the existing driver; no host or CLI starts."""

from __future__ import annotations

import contextlib
import ctypes
import json
import socket
import threading
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from omnigent.terminals import control_metadata
from omnigent.terminals import terminal_control as control
from omnigent.terminals.conpty import ConPTYSession
from omnigent.terminals.conpty_screen import ConPTYScreen
from tests.terminals.test_conpty import _Driver


@pytest.fixture
def endpoint():
    driver = _Driver()
    session = ConPTYSession(driver, screen=ConPTYScreen())
    server = control.TerminalControlServer(session)
    try:
        yield driver, session, server
    finally:
        driver.allow_write.set()
        server.close()
        session.close()
    assert not server._thread.is_alive() and not session.workers_alive


def test_private_advertisement_io_generation_and_owned_close(tmp_path: Path, endpoint) -> None:
    driver, session, server = endpoint
    server.advertise(tmp_path)
    target = control.read_target(tmp_path)
    assert target == server.target
    assert target.token not in repr(target)
    assert server._listener.getsockname()[0] == "127.0.0.1"
    assert control.request_control(target, "state")["alive"] is True
    for op, values, expected in [
        ("literal", {"text": "Καλημέρα 😀"}, "Καλημέρα 😀"),
        ("keys", {"keys": "BTab C-u Enter Escape"}, "\x1b[Z\x15\r\x1b"),
        ("paste", {"text": "first\rsecond"}, "\x1b[200~first\rsecond\x1b[201~"),
    ]:
        assert control.request_control(target, op, **values)["accepted"]
        assert driver.operations[-1] == expected
    viewer = session.subscribe(replay=False)
    text = "wrapped Καλημέρα " * 12
    driver.output.put(text + "\r\nHARD")
    assert viewer.read(timeout=1) == text + "\r\nHARD"
    joined = control.request_control(target, "capture", join_wrapped=True)["text"]
    assert text.rstrip() + "\nHARD" in joined
    assert (
        text.rstrip() not in control.request_control(target, "capture", join_wrapped=False)["text"]
    )
    previous = list(driver.operations)
    for wrong in [replace(target, token="a" * 43), replace(target, generation="f" * 32)]:
        with pytest.raises(control.TerminalControlError):
            control.request_control(wrong, "literal", text="must not arrive")
    assert driver.operations == previous
    assert control.request_control(target, "close")["closed"] is True
    assert not (tmp_path / control.CONTROL_FILE).exists()
    assert driver.closed
    with pytest.raises(control.TerminalControlError):
        control.request_control(target, "state")


@pytest.mark.parametrize(
    "op,values",
    [
        ("exec", {"command": "anything"}),
        ("read", {"path": "anything"}),
        ("keys", {"keys": "unsupported"}),
        ("paste", {"text": "\x1b[201~escape"}),
        ("literal", {"text": "x", "path": "anything"}),
        ("capture", {"join_wrapped": 1}),
    ],
)
def test_reject_unscoped_or_malformed_requests(endpoint, op: str, values: dict) -> None:
    driver, _, server = endpoint
    with pytest.raises(control.TerminalControlError):
        control.request_control(server.target, op, **values)
    assert driver.operations == []
    assert control.request_control(server.target, "state")["alive"] is True


def test_timeout_does_not_cancel_or_repeat_atomic_paste(endpoint, monkeypatch) -> None:
    driver, session, server = endpoint
    monkeypatch.setattr(control, "_WRITE_SECONDS", 0.02)
    driver.allow_write.clear()
    with pytest.raises(control.DeliveryUncertain, match="inspect before retrying"):
        control.request_control(server.target, "paste", text="one prompt")
    assert driver.writing.is_set() and driver.operations == []
    assert control.request_control(server.target, "state")["input_uncertain"] is True
    for op, values in [("paste", {"text": "one prompt"}), ("keys", {"keys": "Enter"})]:
        with pytest.raises(control.DeliveryUncertain):
            control.request_control(server.target, op, **values)
    driver.allow_write.set()
    session.write("barrier").result(timeout=1)
    assert driver.operations == ["\x1b[200~one prompt\x1b[201~", "barrier"]


def test_revoke_stops_slow_connection_and_preserves_new_advertisement(tmp_path, endpoint) -> None:
    driver, session, server = endpoint
    server.advertise(tmp_path)
    newer = control.TerminalControlServer(session)
    try:
        newer.advertise(tmp_path)
        with socket.create_connection(("127.0.0.1", server.target.port), timeout=1) as slow:
            slow.sendall(b"POST /v1/control HTTP/1.1\r\n")
            server.close()
        assert not server._thread.is_alive()
        assert control.read_target(tmp_path) == newer.target
        assert control.request_control(newer.target, "state")["alive"]
        assert driver.operations == []
    finally:
        newer.close()


@pytest.mark.parametrize(
    "wire",
    [
        b"POST /v1/control HTTP/1.1\r\nContent-Length: 99999999\r\n\r\n",
        b"POST /v1/control HTTP/1.1\r\nContent-Length: 2\r\nContent-Length: 2\r\n\r\n{}",
        b"POST /v1/control HTTP/1.1\r\nTransfer-Encoding: chunked\r\nContent-Length: 2\r\n\r\n{}",
        b"POST /v1/control HTTP/1.1\r\nX: " + b"x" * 4096,
    ],
)
def test_bounded_http_parser_refuses_oversize_and_ambiguous_framing(endpoint, wire) -> None:
    driver, _, server = endpoint
    with socket.create_connection(("127.0.0.1", server.target.port), timeout=1) as connection:
        connection.sendall(wire)
        with contextlib.suppress(ConnectionResetError):
            assert not connection.recv(4096)
    assert driver.operations == []
    assert control.request_control(server.target, "state")["alive"]


def test_connection_absolute_deadline_bounds_drip_input(endpoint, monkeypatch) -> None:
    _, _, server = endpoint
    monkeypatch.setattr(control, "_CONNECTION_SECONDS", 0.15)
    with socket.create_connection(("127.0.0.1", server.target.port), timeout=1) as slow:
        slow.sendall(b"P")
        time.sleep(0.1)
        slow.sendall(b"O")
        time.sleep(0.1)
        assert slow.recv(1) == b""
    assert control.request_control(server.target, "state")["alive"]


def test_client_ignores_proxies_and_never_follows_redirects(endpoint, monkeypatch) -> None:
    _, _, server = endpoint
    for name in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"]:
        monkeypatch.setenv(name, "http://192.0.2.1:1")
    assert control.request_control(server.target, "state")["alive"]
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    target = replace(server.target, port=listener.getsockname()[1])
    received = []

    def redirect() -> None:
        with listener:
            with listener.accept()[0] as connection:
                received.append(connection.recv(8192))
                body = json.dumps({"generation": target.generation}).encode()
                connection.sendall(
                    b"HTTP/1.1 302 Found\r\nLocation: http://192.0.2.1/\r\nContent-Length: "
                    + str(len(body)).encode()
                    + b"\r\n\r\n"
                    + body
                )

    thread = threading.Thread(target=redirect)
    thread.start()
    try:
        with pytest.raises(control.TerminalControlError):
            control.request_control(target, "literal", text="once")
    finally:
        thread.join(timeout=1)
    assert not thread.is_alive() and len(received) == 1
    header, body = received[0].split(b"\r\n\r\n", 1)
    assert target.token.encode() in header and target.token.encode() not in body


def test_windows_metadata_requires_user_bound_protection(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(control_metadata, "IS_WINDOWS", True)
    path = tmp_path / control.CONTROL_FILE
    path.write_bytes(b'{"token":"plaintext forbidden"}')
    with pytest.raises(control_metadata.PrivateMetadataError, match="DPAPI"):
        control_metadata.read_private_metadata(path)
    crypt = Mock(side_effect=control_metadata.PrivateMetadataError("DPAPI unavailable"))
    monkeypatch.setattr(control_metadata, "_dpapi", crypt)
    path.unlink()
    with pytest.raises(control_metadata.PrivateMetadataError):
        control_metadata.write_private_metadata(path, b"private")
    assert not path.exists() and list(tmp_path.iterdir()) == []
    assert crypt.call_args.kwargs["decrypt"] is False


@pytest.mark.parametrize("decrypt", [False, True])
def test_dpapi_uses_only_system_dlls_user_scope_no_ui_and_frees_output(
    monkeypatch, decrypt
) -> None:
    output = ctypes.create_string_buffer(b"sealed-or-opened")
    calls = []

    def transform(incoming, description, entropy, reserved, prompt, flags, outgoing):
        calls.append((description, reserved, prompt, flags))
        binding = ctypes.cast(entropy, ctypes.POINTER(control_metadata._Blob)).contents
        assert ctypes.string_at(binding.data, binding.size) == b"directory-bound"
        result = ctypes.cast(outgoing, ctypes.POINTER(control_metadata._Blob)).contents
        result.size = len(b"sealed-or-opened")
        result.data = ctypes.cast(output, ctypes.c_void_p)
        return 1

    api = Mock(side_effect=transform)
    free = Mock()
    crypt = Mock(CryptProtectData=api, CryptUnprotectData=api)
    kernel = Mock(LocalFree=free)
    loader = Mock(side_effect=[crypt, kernel])
    monkeypatch.setattr(ctypes, "WinDLL", loader, raising=False)
    assert (
        control_metadata._dpapi(b"input", decrypt=decrypt, context=b"directory-bound")
        == b"sealed-or-opened"
    )
    assert calls == [(None, None, None, 1)]
    assert all(
        call.kwargs == {"use_last_error": True, "winmode": 0x800} for call in loader.call_args_list
    )
    free.assert_called_once()
    assert output.raw[:-1] == b"\0" * len(b"sealed-or-opened")


@pytest.mark.posix_only
def test_private_metadata_refuses_permissions_redirection_and_malformed_target(tmp_path) -> None:
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    path = directory / control.CONTROL_FILE
    path.write_bytes(b"invalid")
    path.chmod(0o644)
    with pytest.raises(control_metadata.PrivateMetadataError):
        control.read_target(directory)
    path.chmod(0o600)
    with pytest.raises(control.TerminalControlError):
        control.read_target(directory)
    path.unlink()
    path.symlink_to(tmp_path / "other")
    with pytest.raises(control_metadata.PrivateMetadataError):
        control.read_target(directory)
    assert not (tmp_path / "other").exists()


@pytest.mark.windows_only
def test_current_user_dpapi_roundtrip_tamper_and_directory_binding(tmp_path) -> None:
    path = tmp_path / control.CONTROL_FILE
    secret = b"fixture-private-capability"
    control_metadata.write_private_metadata(path, secret)
    ciphertext = path.read_bytes()
    assert secret not in ciphertext
    assert control_metadata.read_private_metadata(path) == secret
    other = tmp_path / "other"
    other.mkdir()
    (other / control.CONTROL_FILE).write_bytes(ciphertext)
    with pytest.raises(control_metadata.PrivateMetadataError):
        control_metadata.read_private_metadata(other / control.CONTROL_FILE)
    damaged = bytearray(ciphertext)
    damaged[-8] ^= 1
    path.write_bytes(damaged)
    with pytest.raises(control_metadata.PrivateMetadataError):
        control_metadata.read_private_metadata(path)
