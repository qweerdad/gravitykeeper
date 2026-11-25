"""Inspect local installation metadata and session catalogue without opening live SQL."""

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sqlite3

from .capture import discover, inventory, snapshot_file
from .exporter import connect
from .paths import isolated_directory


def version_resource(path):
    if os.name != "nt":
        return None
    api = ctypes.WinDLL("version", use_last_error=True)
    api.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    api.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    api.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
    api.VerQueryValueW.argtypes = [wintypes.LPCVOID, wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPVOID),
                                   ctypes.POINTER(wintypes.UINT)]
    size = api.GetFileVersionInfoSizeW(str(path), None)
    value, length = wintypes.LPVOID(), wintypes.UINT()
    if not size:
        return None
    buf = ctypes.create_string_buffer(size)
    if not api.GetFileVersionInfoW(str(path), 0, size, buf):
        return None
    if not api.VerQueryValueW(buf, "\\", ctypes.byref(value), ctypes.byref(length)) or length.value < 52:
        return None
    fixed = ctypes.cast(value, ctypes.POINTER(wintypes.DWORD))
    if fixed[0] != 0xFEEF04BD:
        return None
    a, b = fixed[2], fixed[3]
    return f"{a >> 16}.{a & 65535}.{b >> 16}.{b & 65535}"


def installations():
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    local = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
    program = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    candidates = [basedir / "antigravity" / "Antigravity.exe"
                  for basedir in (local / "Programs", home / "AppData" / "Local" / "Programs", program)]
    found = []
    for path in dict.fromkeys(candidates):
        if path.is_file():
            found.append({"path": str(path), "version": version_resource(path)})
    return found


def probe(override=None, include_workspaces=False, include_installations=True, scratch=None):
    data = discover(override)
    workspaces = set()
    catalogue_available = False
    if include_workspaces:
        for label, root, paths in inventory(override):
            source = root / "conversation_summaries.db"
            if source not in paths:
                continue
            try:
                with isolated_directory(scratch, "gkp_") as base:
                    final = base / source.name
                    _, standalone, warning = snapshot_file(source, final, base / "r.db", attempts=1)
                    if warning:
                        continue
                    with connect(standalone or final) as db:
                        for row in db.execute("SELECT workspace_uris FROM conversation_summaries"):
                            uris = json.loads(row[0] or "[]")
                            if isinstance(uris, list):
                                workspaces.update(uri for uri in uris if isinstance(uri, str) and uri)
                    catalogue_available = True
            except (OSError, ValueError, sqlite3.Error):
                continue
    return {"installations": installations() if include_installations else [], "locations": data,
            "conversations": sum(row["conversation_count"] for row in data),
            "workspaces": len(workspaces) if catalogue_available else None,
            "bytes": sum(row["bytes"] for row in data)}
