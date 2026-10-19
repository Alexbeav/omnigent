"""Bounded loopback control of one owned ConPTY generation.

This deliberately small HTTP subset has one serving thread, one active
connection and four pending connections. No URLs, commands or filesystem paths
are accepted. Capabilities travel only in Authorization, never JSON or logs.
"""

from __future__ import annotations

import contextlib
import hmac
import json
import re
import secrets
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from omnigent.terminals.control_metadata import (
    PrivateMetadataError,
    read_private_metadata,
    write_private_metadata,
)

if TYPE_CHECKING:
    from omnigent.terminals.conpty import ConPTYSession

CONTROL_FILE = "terminal-control.private"
_BODY_LIMIT = 196_608
_RESPONSE_LIMIT = 1_048_576
_HEADER_LIMIT = 4096
_CONNECTION_SECONDS = 4.0
_WRITE_SECONDS = 1.0
_CLIENT_SECONDS = 6.0


class TerminalControlError(RuntimeError):
    """A terminal control request failed without exposing its capability."""


class DeliveryUncertain(TerminalControlError):
    """Input may still be queued or executing. Never automatically replay it."""


@dataclass(frozen=True)
class ConPTYControlTarget:
    port: int
    generation: str
    token: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.port) is not int
            or not 1 <= self.port <= 65535
            or not isinstance(self.generation, str)
            or re.fullmatch(r"[a-f0-9]{32}", self.generation) is None
            or not isinstance(self.token, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{43}", self.token) is None
        ):
            raise TerminalControlError("Invalid terminal control target")


def advertise_target(directory: Path, target: ConPTYControlTarget) -> None:
    write_private_metadata(
        directory / CONTROL_FILE,
        json.dumps(
            {
                "backend": "conpty",
                "version": 1,
                "port": target.port,
                "generation": target.generation,
                "token": target.token,
            }
        ).encode("utf-8"),
    )


def read_target(directory: Path) -> ConPTYControlTarget | None:
    try:
        (directory / CONTROL_FILE).lstat()
        raw = read_private_metadata(directory / CONTROL_FILE)
    except FileNotFoundError:
        return None
    try:
        value = json.loads(raw)
        if (
            not isinstance(value, dict)
            or set(value) != {"backend", "version", "port", "generation", "token"}
            or value["backend"] != "conpty"
            or type(value["version"]) is not int
            or value["version"] != 1
        ):
            raise ValueError
        return ConPTYControlTarget(value["port"], value["generation"], value["token"])
    except (ValueError, TypeError, KeyError):
        raise TerminalControlError("Invalid private terminal control metadata") from None


class _Channel:
    def __init__(self, connection: socket.socket, seconds: float) -> None:
        self.connection = connection
        self.deadline = time.monotonic() + seconds

    def _budget(self) -> None:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        self.connection.settimeout(remaining)

    def receive(self, limit: int) -> tuple[str, dict[str, str], bytes]:
        data = b""
        while b"\r\n\r\n" not in data:
            if len(data) >= _HEADER_LIMIT:
                raise ValueError
            self._budget()
            chunk = self.connection.recv(min(1024, _HEADER_LIMIT - len(data)))
            if not chunk:
                raise ValueError
            data += chunk
        header, body = data.split(b"\r\n\r\n", 1)
        lines = header.decode("ascii").split("\r\n")
        if len(lines) > 9:
            raise ValueError
        headers: dict[str, str] = {}
        for line in lines[1:]:
            key, separator, value = line.partition(":")
            if not separator or not re.fullmatch(r"[A-Za-z-]+", key):
                raise ValueError
            key = key.lower()
            if key in headers:
                raise ValueError
            headers[key] = value.strip()
        length = headers.get("content-length", "")
        if not re.fullmatch(r"[0-9]{1,8}", length) or not 0 < int(length) <= limit:
            raise ValueError
        if "transfer-encoding" in headers or "expect" in headers:
            raise ValueError
        size = int(length)
        if len(body) > size:
            raise ValueError
        while len(body) < size:
            self._budget()
            chunk = self.connection.recv(min(65536, size - len(body)))
            if not chunk:
                raise ValueError
            body += chunk
        return lines[0], headers, body

    def send(self, data: bytes) -> None:
        self._budget()
        self.connection.sendall(data)


def _response(status: int, body: dict[str, object]) -> bytes:
    encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if len(encoded) > _RESPONSE_LIMIT:
        status, encoded = 413, b'{"error":"response_too_large"}'
    return (
        f"HTTP/1.1 {status} Control\r\nContent-Length: {len(encoded)}\r\n"
        "Content-Type: application/json\r\nConnection: close\r\n\r\n"
    ).encode("ascii") + encoded


class TerminalControlServer:
    """Own the endpoint only; normal teardown revokes before closing ConPTY."""

    def __init__(self, session: ConPTYSession) -> None:
        self._session = session
        self._lock = threading.Lock()
        self._revoked = threading.Event()
        self._input_uncertain = False
        self._stop = threading.Event()
        self._active: socket.socket | None = None
        self._advertisements: set[Path] = set()
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(4)
        self._listener.settimeout(0.1)
        self.target = ConPTYControlTarget(
            self._listener.getsockname()[1], secrets.token_hex(16), secrets.token_urlsafe(32)
        )
        self._thread = threading.Thread(target=self._serve, name="terminal-control", daemon=True)
        self._thread.start()

    def advertise(self, directory: Path) -> None:
        with self._lock:
            if self._revoked.is_set():
                raise TerminalControlError("Terminal control generation was revoked")
            advertise_target(directory, self.target)
            self._advertisements.add(directory)

    def _remove_advertisements(self) -> None:
        for directory in self._advertisements:
            with contextlib.suppress(OSError, PrivateMetadataError, TerminalControlError):
                if read_target(directory) == self.target:
                    (directory / CONTROL_FILE).unlink(missing_ok=True)

    def close(self) -> None:
        # Revocation precedes all endpoint, metadata and process cleanup.
        with self._lock:
            self._revoked.set()
            self._stop.set()
            if self._active is not None:
                with contextlib.suppress(OSError):
                    self._active.shutdown(socket.SHUT_RDWR)
            self._listener.close()
        self._thread.join(timeout=_CONNECTION_SECONDS)
        self._remove_advertisements()
        if self._thread.is_alive():
            raise TerminalControlError("Terminal control worker did not stop")

    def _serve(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    connection, _ = self._listener.accept()
                except TimeoutError:
                    continue
                except OSError:
                    return
                with connection:
                    with self._lock:
                        if self._revoked.is_set():
                            return
                        self._active = connection
                    try:
                        self._handle(_Channel(connection, _CONNECTION_SECONDS))
                    except (OSError, ValueError, UnicodeError):
                        pass
                    finally:
                        with self._lock:
                            self._active = None
        finally:
            self._listener.close()

    def _handle(self, channel: _Channel) -> None:
        line, headers, body = channel.receive(_BODY_LIMIT)
        if (
            line != "POST /v1/control HTTP/1.1"
            or headers.get("host") != f"127.0.0.1:{self.target.port}"
            or headers.get("content-type") != "application/json"
        ):
            channel.send(_response(400, {"error": "invalid_request"}))
            return
        if not hmac.compare_digest(
            headers.get("authorization", ""), "Bearer " + self.target.token
        ):
            channel.send(_response(403, {"error": "unauthorized"}))
            return
        mutating = False
        try:
            request = json.loads(body)
            if not isinstance(request, dict):
                raise ValueError
            op = request.get("op")
            mutating = isinstance(op, str) and op in {"literal", "keys", "paste"}
            status, result = self._dispatch(request)
        except (ValueError, TypeError, UnicodeError):
            status, result = 400, {"error": "invalid_request"}
        except RuntimeError:
            # A driver failure can follow partial acceptance, just like a timeout.
            if mutating:
                with self._lock:
                    self._input_uncertain = True
            status, result = 409, {"error": "delivery_uncertain"}
        try:
            channel.send(_response(status, {**result, "generation": self.target.generation}))
        except OSError:
            if mutating:
                with self._lock:
                    self._input_uncertain = True
            raise

    def _dispatch(self, request: dict[str, object]) -> tuple[int, dict[str, object]]:
        op = request.get("op")
        fields = {
            "literal": {"text"},
            "keys": {"keys"},
            "paste": {"text"},
            "capture": {"join_wrapped"},
            "state": set(),
            "close": set(),
        }
        if not isinstance(op, str) or op not in fields:
            raise ValueError
        if set(request) != {"op", "generation"} | fields[op]:
            raise ValueError
        future = None
        with self._lock:
            if self._revoked.is_set() or request["generation"] != self.target.generation:
                return 410, {"error": "stale_generation"}
            if op == "state":
                return 200, {
                    "alive": self._session.alive,
                    "exit_status": self._session.exit_status,
                    "input_uncertain": self._input_uncertain,
                }
            if op == "capture":
                if type(request["join_wrapped"]) is not bool:
                    raise ValueError
                snapshot = self._session.capture(join_wrapped=request["join_wrapped"])
                return 200, {"text": snapshot.text}
            if op == "close":
                self._revoked.set()
                self._stop.set()
            else:
                if self._input_uncertain:
                    return 409, {"error": "delivery_uncertain"}
                if not self._session.alive:
                    return 410, {"error": "terminal_exited"}
                if op == "keys":
                    from omnigent.terminals.conpty_instance import _encode_keys

                    if not isinstance(request["keys"], str):
                        raise ValueError
                    text = _encode_keys(request["keys"])
                else:
                    if not isinstance(request["text"], str) or "\0" in request["text"]:
                        raise ValueError
                    text = request["text"]
                    if op == "paste":
                        if "\x1b[201~" in text:
                            raise ValueError
                        text = "\x1b[200~" + text + "\x1b[201~"
                future = self._session.write(text)
        if op == "close":
            self._remove_advertisements()
            self._session.close(timeout=2.0)
            return 200, {"closed": True}
        try:
            assert future is not None
            future.result(timeout=_WRITE_SECONDS)
        except TimeoutError:
            # Cancellation cannot establish that queued input was not delivered.
            with self._lock:
                self._input_uncertain = True
            return 409, {"error": "delivery_uncertain"}
        return 200, {"accepted": True}


def request_control(target: ConPTYControlTarget, op: str, **values: object) -> dict[str, object]:
    """One request, no proxies, redirects or retries, even after ambiguous I/O."""
    mutating = op in {"literal", "keys", "paste", "close"}
    body = json.dumps({"op": op, "generation": target.generation, **values}).encode("utf-8")
    if len(body) > _BODY_LIMIT:
        raise TerminalControlError("Terminal input exceeds the request bound")
    encoded = (
        f"POST /v1/control HTTP/1.1\r\nHost: 127.0.0.1:{target.port}\r\n"
        f"Authorization: Bearer {target.token}\r\nContent-Length: {len(body)}\r\n"
        "Content-Type: application/json\r\nConnection: close\r\n\r\n"
    ).encode("ascii") + body
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            channel = _Channel(connection, _CLIENT_SECONDS)
            connection.settimeout(_CLIENT_SECONDS)
            connection.connect(("127.0.0.1", target.port))
            channel.send(encoded)
            line, _, reply = channel.receive(_RESPONSE_LIMIT)
        value = json.loads(reply)
        if not isinstance(value, dict) or value.get("generation") != target.generation:
            raise ValueError
        if value.get("error") == "delivery_uncertain":
            raise DeliveryUncertain("Terminal delivery is uncertain; inspect before retrying")
        if line != "HTTP/1.1 200 Control" or "error" in value:
            raise TerminalControlError("Terminal control request rejected or generation stale")
        return value
    except (OSError, ValueError, UnicodeError):
        if mutating:
            raise DeliveryUncertain(
                "Terminal delivery is uncertain; inspect before retrying"
            ) from None
        raise TerminalControlError("Terminal control is unavailable") from None
