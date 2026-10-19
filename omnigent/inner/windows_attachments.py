"""Native Windows attachment writes without following reparse points."""

from __future__ import annotations

import contextlib
import ctypes
import ctypes.wintypes as wintypes
import errno
import functools
import hashlib
import os
import stat
from collections.abc import Callable, Iterator
from pathlib import Path, PureWindowsPath
from typing import Literal, Protocol, cast


class _WinFunction(Protocol):
    restype: object
    argtypes: list[object]

    def __call__(self, *args: object) -> int | None: ...


class _Kernel32(Protocol):
    CreateFileW: _WinFunction
    GetFileInformationByHandleEx: _WinFunction
    GetFileType: _WinFunction
    CloseHandle: _WinFunction


class _AttributeTagInfo(ctypes.Structure):
    _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]


@functools.cache
def _kernel32() -> _Kernel32:
    library = cast(Callable[..., _Kernel32], vars(ctypes)["WinDLL"])
    kernel = library("kernel32", use_last_error=True)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel.GetFileType.restype = wintypes.DWORD
    kernel.GetFileType.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    return kernel


def _windows_error() -> OSError:
    last_error = cast(Callable[[], int], vars(ctypes)["get_last_error"])
    win_error = cast(Callable[[int], OSError], vars(ctypes)["WinError"])
    return win_error(last_error())


def _open_handle(path: Path, *, directory: bool = False, create: bool = False) -> int:
    kernel = _kernel32()
    # No FILE_SHARE_DELETE: opened directories/files cannot be renamed underneath us.
    handle = kernel.CreateFileW(
        str(path),
        0x80 if directory else 0x40000080 if create else 0x80000000,
        3 if directory else 1,
        None,
        1 if create else 3,
        0x00200000 | (0x02000000 if directory else 0),
        None,
    )
    if handle is None or handle == ctypes.c_void_p(-1).value:
        raise _windows_error()
    try:
        info = _AttributeTagInfo()
        if not kernel.GetFileInformationByHandleEx(
            handle, 9, ctypes.byref(info), ctypes.sizeof(info)
        ):
            raise _windows_error()
        if info.attributes & 0x400:
            raise OSError(errno.ELOOP, "Attachment cache reparse point refused")
        if bool(info.attributes & 0x10) != directory or kernel.GetFileType(handle) != 1:
            raise OSError(errno.EINVAL, "Unexpected attachment cache entry type")
        return handle
    except BaseException:
        kernel.CloseHandle(handle)
        raise


@contextlib.contextmanager
def _hold_directory(path: Path) -> Iterator[None]:
    handle = _open_handle(path, directory=True)
    try:
        yield
    finally:
        if not _kernel32().CloseHandle(handle):
            raise _windows_error()


def _open_file(path: Path, *, create: bool = False) -> int:
    import msvcrt

    handle = _open_handle(path, create=create)
    try:
        open_osfhandle = cast(Callable[[int, int], int], vars(msvcrt)["open_osfhandle"])
        binary = cast(int, vars(os)["O_BINARY"])
        return open_osfhandle(handle, (os.O_WRONLY if create else os.O_RDONLY) | binary)
    except BaseException:
        _kernel32().CloseHandle(handle)
        raise


def _place(path: Path, raw_bytes: bytes) -> Literal["placed", "taken", "symlink"]:
    try:
        fd = _open_file(path)
    except FileNotFoundError:
        try:
            fd = _open_file(path, create=True)
        except FileExistsError:
            return "taken"
        try:
            view = memoryview(raw_bytes)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError(errno.EIO, "Attachment write made no progress")
                view = view[written:]
        except OSError:
            os.close(fd)
            with contextlib.suppress(OSError):
                path.unlink()
            raise
        os.close(fd)
        return "placed"
    except OSError as error:
        if error.errno == errno.ELOOP:
            return "symlink"
        raise
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size != len(raw_bytes):
            return "taken"
        with os.fdopen(fd, "rb", closefd=False) as stream:
            return "placed" if stream.read(len(raw_bytes) + 1) == raw_bytes else "taken"
    finally:
        os.close(fd)


def materialize_windows_attachment(
    directory: Path, filename: str, raw_bytes: bytes
) -> Path | None:
    """Keep cache directories open and reject links, devices and alternate streams."""
    if (
        not filename
        or filename in {".", ".."}
        or filename.endswith((".", " "))
        or any(ord(char) < 32 or char in '<>:"/\\|?*' for char in filename)
        or PureWindowsPath(filename).is_reserved()
    ):
        raise OSError(errno.EINVAL, "Invalid Windows attachment filename")
    directory.parent.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.ExitStack() as stack:
        stack.enter_context(_hold_directory(directory.parent.parent))
        for path in (directory.parent, directory):
            path.mkdir(exist_ok=True)
            stack.enter_context(_hold_directory(path))
        stem, suffix = os.path.splitext(filename)
        digest = hashlib.sha256(raw_bytes).hexdigest()[:12]
        for name in (filename, f"{stem}_{digest}{suffix}"):
            outcome = _place(directory / name, raw_bytes)
            if outcome == "symlink":
                return None
            if outcome == "placed":
                return directory / name
    return None
