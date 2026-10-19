"""Account-bound terminal capabilities; never publish these as resources.

Windows records are entirely sealed with current-user DPAPI, including the
generation and port. POSIX records require owner-only directories and files.
Neither Windows chmod nor inherited ACLs establish this security boundary.
"""

from __future__ import annotations

import ctypes
import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from filelock import FileLock
from filelock import Timeout as FileLockTimeout

from omnigent._platform import IS_WINDOWS

_LIMIT = 8192
_PREFIX = b"omnigent-dpapi-v1\n"


class PrivateMetadataError(RuntimeError):
    """Private terminal metadata could not be authenticated or protected."""


class _Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.c_void_p)]


def _dpapi(data: bytes, *, decrypt: bool, context: bytes) -> bytes:
    # Load only system DLLs, with explicit pointer-sized prototypes on Win64.
    loader = cast(Any, ctypes).WinDLL
    crypt = loader("crypt32", use_last_error=True, winmode=0x800)
    kernel = loader("kernel32", use_last_error=True, winmode=0x800)
    transform = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    transform.argtypes = [
        ctypes.POINTER(_Blob),
        ctypes.c_void_p,
        ctypes.POINTER(_Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(_Blob),
    ]
    transform.restype = ctypes.c_int
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    source, entropy = ctypes.create_string_buffer(data), ctypes.create_string_buffer(context)
    incoming = _Blob(len(data), ctypes.cast(source, ctypes.c_void_p))
    binding = _Blob(len(context), ctypes.cast(entropy, ctypes.c_void_p))
    outgoing = _Blob()
    # UI_FORBIDDEN only. LOCAL_MACHINE would permit other accounts to decrypt.
    if not transform(
        ctypes.byref(incoming),
        None,
        ctypes.byref(binding),
        None,
        None,
        1,
        ctypes.byref(outgoing),
    ):
        raise PrivateMetadataError("Terminal metadata DPAPI protection failed")
    try:
        if outgoing.size > _LIMIT:
            raise PrivateMetadataError("Terminal metadata exceeds its bound")
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        if outgoing.data:
            ctypes.memset(outgoing.data, 0, outgoing.size)
            kernel.LocalFree(outgoing.data)


def _context(directory: Path) -> bytes:
    return ("omnigent-terminal-control-v1:" + os.path.normcase(str(directory.absolute()))).encode(
        "utf-8"
    )


def _validate_directory(directory: Path) -> None:
    current = directory.absolute()
    leaf = True
    while True:
        info = current.lstat()
        if not stat.S_ISDIR(info.st_mode) or current.is_symlink() or current.is_junction():
            raise PrivateMetadataError("Terminal metadata directory is redirected")
        if not IS_WINDOWS:
            if leaf and (info.st_uid != os.getuid() or info.st_mode & 0o077):
                raise PrivateMetadataError("Terminal metadata directory is not private")
            if (
                not leaf
                and info.st_mode & 0o022
                and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX)
            ):
                raise PrivateMetadataError("Terminal metadata ancestor is writable by others")
        if current == current.parent:
            break
        current, leaf = current.parent, False


def write_private_metadata(path: Path, data: bytes) -> None:
    """Atomically advertise sealed bytes; never write plaintext on Windows."""
    _validate_directory(path.parent)
    if len(data) > _LIMIT:
        raise PrivateMetadataError("Terminal metadata exceeds its bound")
    payload = (
        _PREFIX + _dpapi(data, decrypt=False, context=_context(path.parent))
        if IS_WINDOWS
        else data
    )
    if len(payload) > _LIMIT:
        raise PrivateMetadataError("Terminal metadata exceeds its bound")
    fd, name = tempfile.mkstemp(prefix=".terminal-control-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
            output.flush()
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def private_metadata_lock(directory: Path) -> Iterator[None]:
    """Serialize publication and conditional removal across endpoint owners."""
    _validate_directory(directory)
    try:
        with FileLock(str(directory / ".terminal-control.lock"), timeout=4, mode=0o600):
            _validate_directory(directory)
            yield
    except FileLockTimeout:
        raise PrivateMetadataError("Terminal metadata publication is busy") from None


def read_private_metadata(path: Path) -> bytes:
    """Refuse plaintext Windows records and unqualified POSIX metadata."""
    _validate_directory(path.parent)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or path.is_symlink() or path.is_junction():
        raise PrivateMetadataError("Terminal metadata is not a regular file")
    with path.open("rb") as source:
        info = os.fstat(source.fileno())
        if (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino):
            raise PrivateMetadataError("Terminal metadata changed while opening")
        if not IS_WINDOWS and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise PrivateMetadataError("Terminal metadata file is not private")
        data = source.read(_LIMIT + 1)
    if len(data) > _LIMIT:
        raise PrivateMetadataError("Terminal metadata exceeds its bound")
    if IS_WINDOWS:
        if not data.startswith(_PREFIX):
            raise PrivateMetadataError("Terminal metadata requires current-user DPAPI")
        return _dpapi(data[len(_PREFIX) :], decrypt=True, context=_context(path.parent))
    return data
