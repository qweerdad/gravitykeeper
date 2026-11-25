"""Scriptable interface. Results use JSON on stdout and diagnostics on stderr."""

import argparse
import json
from pathlib import Path
import sys
from zipfile import BadZipFile

from . import __version__
from .catalog import search
from .detection import probe
from .errors import error_code
from .service import capture, export, full_backup
from .storage import package_snapshot, verify_snapshot, verify_zip


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="gravitykeeper", description="Local Antigravity snapshot and recovery tool")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    for key, description in (
        ("discover", "Inspect known local installation and read-only data locations"),
        ("backup", "Capture raw files into a new snapshot"),
        ("run", "Capture and export into a new snapshot"),
        ("export", "Export a sealed raw snapshot"),
        ("search", "Search titles, workspaces and message text in a snapshot"),
        ("zip", "Create and verify a ZIP and SHA-256 sidecar"),
        ("verify", "Verify a snapshot directory or ZIP"),
    ):
        cmd = commands.add_parser(key, help=description)
        if key in {"discover", "backup", "run"}:
            cmd.add_argument("--source", type=Path, help="Override the detected data root")
        if key != "discover":
            cmd.add_argument("path", type=Path, help="Snapshot path (or ZIP path for verify)")
        if key == "zip":
            cmd.add_argument("destination", type=Path)
        if key == "search":
            cmd.add_argument("query")
        cmd.add_argument("--progress", action="store_true", help="Print phase progress to stderr")
    args = parser.parse_args(argv)
    previous = None

    def progress(phase, done, total):
        nonlocal previous
        position = (phase, (done * 20 // total if total else 0))
        if args.progress and position != previous:
            print(f"{phase}: {done}/{total}" if total else phase, file=sys.stderr)
            previous = position

    status = 0
    try:
        if args.command == "discover":
            result = probe(args.source, include_workspaces=True)
        elif args.command == "verify":
            result = verify_zip(args.path.resolve(), progress) if args.path.is_file() else verify_snapshot(args.path.resolve(), progress)
            if "manifest" in result:
                raw = result.pop("manifest")
                result["raw_status"] = raw.get("raw_status", "PARTIAL" if raw["errors"] else "COMPLETE")
        elif args.command == "zip":
            result = package_snapshot(args.path, args.destination, progress)
        elif args.command == "search":
            result = search(args.path.resolve(), args.query, progress=progress)
        else:
            if args.command == "backup":
                result = capture(args.path, args.source, progress)
            elif args.command == "run":
                result = full_backup(args.path, args.source, progress)
            else:
                result = export(args.path, progress)
            status = 0 if result["raw"] == "COMPLETE" and result["export"] in {"COMPLETE", "NOT_RUN"} else 3
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return status
    except (OSError, ValueError, KeyError, TypeError, BadZipFile) as error:
        print(json.dumps({"error": error_code(error, "operation_failed"), "message": str(error)},
                         ensure_ascii=False), file=sys.stderr)
        return 2
