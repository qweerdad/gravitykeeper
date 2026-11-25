"""Portable diagnostics for filesystem operations."""

import errno
import os
from pathlib import Path
import shutil


class StorageError(OSError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def error_code(error, fallback="file_error"):
    if isinstance(error, StorageError):
        return error.code
    if getattr(error, "errno", None) == errno.ENOSPC or getattr(error, "winerror", None) in {39, 112}:
        return "disk_full"
    if getattr(error, "sqlite_errorname", None) == "SQLITE_FULL":
        return "disk_full"
    if getattr(error, "winerror", None) in {32, 33}:
        return "file_locked"
    if isinstance(error, FileExistsError):
        return "destination_exists"
    if isinstance(error, PermissionError):
        return "access_denied"
    return fallback


def capture_error_code(path, error):
    code = error_code(error, "unstable_source")
    # The Windows CRT can report a shared-handle conflict as generic EACCES.
    if code != "access_denied" or os.name != "nt":
        return code
    import ctypes
    from ctypes import wintypes
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    api.CreateFileW.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = api.CreateFileW(str(path), 0x80000000, 7, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        return "file_locked" if ctypes.get_last_error() in {32, 33} else code
    api.CloseHandle(handle)
    return code


def ensure_space(destination, required):
    existing = Path(destination)
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    available = shutil.disk_usage(existing).free
    if available < required:
        raise StorageError("disk_full", f"Need approximately {required:,} bytes; {available:,} bytes are available")
