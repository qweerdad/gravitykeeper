"""The shared operations for the command line and desktop application."""

from datetime import datetime
from pathlib import Path
import sqlite3
from uuid import uuid4

from .capture import backup
from .catalog import build_catalog
from .errors import StorageError, ensure_space, error_code
from .exporter import dump_json, export_archive
from .storage import seal, verify_snapshot


REPORT = "JOB_REPORT.json"


def new_snapshot(vault):
    return vault / ("GravityKeeper-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6])


def record(root, summary, progress):
    dump_json(root / REPORT, summary)
    seal(root, progress)
    return summary


def capture(root, source=None, progress=None):
    root = root.resolve()
    if root.exists():
        raise StorageError("destination_exists", "Choose a new snapshot directory")
    if progress:
        progress("discover", 0, 0)
    manifest = backup(root, source, progress)
    return record(root, {"raw": manifest.get("raw_status", "COMPLETE"), "export": "NOT_RUN",
                         "files": manifest["file_count"], "bytes": manifest["bytes"],
                         "capture_errors": manifest["errors"], "database_warnings": manifest["database_warnings"],
                         "sessions": {}, "path": str(root)}, progress)


def export(root, progress=None):
    root = root.resolve()
    captured = verify_snapshot(root, progress)["manifest"]
    if (root / "02_Conversations_Markdown").exists():
        raise StorageError("destination_exists", "This snapshot already has an export. Create a new snapshot for a new export.")
    summary = {"raw": captured.get("raw_status", "PARTIAL" if captured["errors"] else "COMPLETE"),
               "export": "FAILED", "files": captured["file_count"], "bytes": captured["bytes"],
               "capture_errors": captured["errors"], "database_warnings": captured.get("database_warnings", []),
               "sessions": {}, "path": str(root)}
    try:
        ensure_space(root, captured["bytes"] + max(captured["bytes"] // 2, 16 * 1024 * 1024))
        details = export_archive(root, captured, progress)
        data = build_catalog(root, details)
        counts = data["counts"]
        summary["sessions"] = counts
        if not counts:
            summary["export_error"] = {"code": "no_sessions", "message": "No local conversations found in the captured files."}
        elif counts.get("COMPLETE", 0) == sum(counts.values()):
            summary["export"] = "COMPLETE" if summary["raw"] == "COMPLETE" else "PARTIAL"
        elif counts.get("COMPLETE", 0) or counts.get("PARTIAL", 0):
            summary["export"] = "PARTIAL"
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        summary["export_error"] = {"code": error_code(error, "export_error"), "message": str(error)}
    return record(root, summary, progress)


def full_backup(root, source=None, progress=None):
    result = capture(root, source, progress)
    return export(root, progress) if result["raw"] != "FAILED" else result
