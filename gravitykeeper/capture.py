"""Discover and copy known session data without invoking SQLite on a live file."""

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import time
from uuid import UUID

from .errors import StorageError, capture_error_code, ensure_space, error_code
from .paths import isolated_directory


SIDECARS = ("-wal", "-journal")
PRIVATE = re.compile(
    r"(?i)(^\.env(?:\.|$)|credential|cookie|token|password|secret|auth|^id_(?:rsa|ed25519)|"
    r"\.(?:pem|key|pfx|p12|kdbx)$|^login data$|^local state$)"
)
INDEX_FILES = ("conversation_summaries.db", "agyhub_summaries_proto.pb")
GEN_DIRS = {"logs", "steps", "messages", "tasks", "subagents"}
ATTACHMENT_TYPES = {
    ".md", ".markdown", ".json", ".jsonl", ".pbtxt", ".txt", ".log", ".png",
    ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".docx", ".csv", ".svg",
}


def safe_entry(path):
    try:
        return not (
            path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        )
    except FileNotFoundError:
        return False


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def is_uuid(name):
    try:
        return str(UUID(name)) == name.lower()
    except ValueError:
        return False


def sources(override=None):
    if override is not None:
        return [("Gemini_Antigravity", override.resolve())]
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    roaming = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
    return [
        ("Gemini_Antigravity", home / ".gemini" / "antigravity"),
        ("Gemini_Antigravity_IDE", home / ".gemini" / "antigravity-ide"),
        ("Roaming_Antigravity", roaming / "Antigravity"),
        ("Roaming_Antigravity_IDE", roaming / "Antigravity IDE"),
    ]


def walk_allowed(top):
    if not top.is_dir() or not safe_entry(top):
        return
    for folder, subdirs, files in os.walk(top, followlinks=False):
        here = Path(folder)
        subdirs[:] = sorted(name for name in subdirs if safe_entry(here / name) and not PRIVATE.search(name))
        for name in sorted(files):
            path = here / name
            if safe_entry(path) and not PRIVATE.search(name) and path.suffix.lower() in ATTACHMENT_TYPES:
                yield path


def discover_files(root):
    if not root.is_dir() or not safe_entry(root):
        return
    for name in INDEX_FILES:
        path = root / name
        if path.is_file() and safe_entry(path):
            yield path
    for name, extensions in (
        ("conversations", {".db", ".pb", ".json", ".jsonl"}),
        ("annotations", {".pbtxt"}),
    ):
        folder = root / name
        if not folder.is_dir() or not safe_entry(folder):
            continue
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() in extensions and is_uuid(path.stem) and path.is_file() and safe_entry(path):
                yield path
    brain = root / "brain"
    if not brain.is_dir() or not safe_entry(brain):
        return
    for session in sorted(brain.iterdir()):
        if not (session.is_dir() and safe_entry(session)):
            continue
        if session.name == "tempmediaStorage":
            yield from walk_allowed(session)
        elif is_uuid(session.name):
            for path in sorted(session.iterdir()):
                if not safe_entry(path) or PRIVATE.search(path.name):
                    continue
                if path.is_file() and path.suffix.lower() in ATTACHMENT_TYPES:
                    yield path
                elif path.name == ".system_generated" and path.is_dir():
                    for child in sorted(GEN_DIRS):
                        yield from walk_allowed(path / child)
                elif path.name == ".user_uploaded" and path.is_dir():
                    yield from walk_allowed(path)


def inventory(override=None):
    result = []
    for label, root in sources(override):
        files = list(discover_files(root))
        result.append((label, root, files))
    return result


def discovered_ids(paths):
    return {
        p.stem if p.parent.name == "conversations" else p.parents[2].name
        for p in paths
        if p.parent.name == "conversations" or p.name in {"transcript_full.jsonl", "transcript.jsonl"}
    }


def file_size(path):
    try:
        return path.stat().st_size
    except OSError:
        return 0


def discover(override=None):
    return [{"label": label, "path": str(root), "exists": root.is_dir(), "selected_files": len(files),
             "conversation_count": len(discovered_ids(files)),
             "conversation_databases": sum(p.parent.name == "conversations" and p.suffix == ".db" for p in files),
             "complete_transcripts": sum(p.name == "transcript_full.jsonl" for p in files),
             "bytes": sum(file_size(p) for p in files)} for label, root, files in inventory(override)]


def sqlite_files(base):
    paths = [base]
    for suffix in SIDECARS:
        candidate = Path(str(base) + suffix)
        if candidate.exists():
            if not candidate.is_file() or not safe_entry(candidate):
                raise OSError(f"unsafe SQLite companion {candidate.name}")
            paths.append(candidate)
    # SHM is derived from the WAL and can be recreated on disposable copies.
    return paths


def fingerprints(paths):
    signatures = []
    for path in paths:
        info = path.stat()
        signatures.append((path, info.st_size, info.st_mtime_ns, info.st_ino, digest(path)))
    return signatures


def checked_database(source_copy, standalone=None):
    """Run SQLite only on an isolated copy. It may replay a local WAL/journal."""
    with isolated_directory(source_copy.parent, "sql_") as folder:
        local = folder / source_copy.name
        for path in sqlite_files(source_copy):
            shutil.copy2(path, local.parent / path.name)
        with closing(sqlite3.connect(local, timeout=2)) as db:
            result = [row[0] for row in db.execute("PRAGMA quick_check")]
            if result != ["ok"]:
                raise sqlite3.DatabaseError("; ".join(result))
            if standalone is not None:
                with closing(sqlite3.connect(standalone, timeout=2)) as export:
                    db.backup(export)
                    export.execute("PRAGMA journal_mode=DELETE")
                    if export.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                        raise sqlite3.DatabaseError("standalone export view quick_check failed")


def snapshot_file(source, final, derived, attempts=3):
    is_db = source.suffix.lower() == ".db"
    final.parent.mkdir(parents=True, exist_ok=True)
    last_error = None
    for attempt in range(attempts):
        published = []
        try:
            with isolated_directory(final.parent, "copy_") as spool:
                if not safe_entry(source):
                    raise OSError("source is no longer a regular file entry")
                before = fingerprints(sqlite_files(source) if is_db else [source])
                for path, *_ in before:
                    shutil.copy2(path, spool / path.name)
                after = fingerprints(sqlite_files(source) if is_db else [source])
                if before != after or any(digest(spool / p.name) != sha for p, *_, sha in before):
                    raise OSError("source files changed during capture")
                built = None
                warning = None
                if is_db:
                    try:
                        with (spool / final.name).open("rb") as stream:
                            if stream.read(16) != b"SQLite format 3\x00":
                                raise StorageError("unsupported_format", "Unrecognized SQLite database header")
                        built = spool / "standalone.sqlite" if len(before) > 1 else None
                        checked_database(spool / final.name, built)
                    except (sqlite3.DatabaseError, StorageError) as error:
                        if error_code(error) == "disk_full":
                            raise
                        warning = {"code": error_code(error, "database_corrupt"), "message": str(error)}
                        built = None
                if built is not None:
                    derived.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(built, derived)
                    published.append(derived)
                for original, *_ in before:
                    path = final.parent / original.name
                    shutil.move(spool / original.name, path)
                    published.append(path)
                return before, derived if built is not None else None, warning
        except (OSError, sqlite3.Error) as error:
            for path in reversed(published):
                path.unlink(missing_ok=True)
            last_error = error
            if error_code(error) == "disk_full":
                break
            time.sleep(0.25 * (attempt + 1))
    raise StorageError(capture_error_code(source, last_error), f"Stable capture failed: {last_error}")


def backup(destination, override=None, progress=None):
    destination = destination.resolve()
    targets = inventory(override)
    if not any(files for _, _, files in targets):
        raise ValueError("No supported Antigravity conversation files were found")
    for _, root in sources() + sources(override):
        if destination.is_relative_to(root.resolve()):
            raise StorageError("unsafe_destination", "Backup destination is inside an Antigravity source directory")
    candidates = [(label, root, p) for label, root, files in targets for p in files]
    source_bytes = sum(file_size(p) for _, _, p in candidates)
    ensure_space(destination, source_bytes + max(source_bytes // 10, 8 * 1024 * 1024))
    destination.mkdir(parents=True, exist_ok=False)
    raw = destination / "01_Raw_Backup"
    raw.mkdir()
    files = []
    errors = []
    database_warnings = []
    roots = [{"label": label, "source": str(root), "exists": root.is_dir()} for label, root, _ in targets]
    for position, (label, root, source) in enumerate(candidates, 1):
        rel = source.relative_to(root)
        output = raw / label / rel
        derived = raw / "SQLite_Standalone" / label / rel
        try:
            selected, standalone, warning = snapshot_file(source, output, derived)
            for original, size, _mtime, _inode, hash_value in selected:
                path = output.parent / original.name
                files.append({"source": str(original), "relative_path": path.relative_to(destination).as_posix(),
                              "bytes": size, "sha256": hash_value})
            if standalone:
                files.append({"source": str(source), "kind": "derived_sqlite_standalone",
                              "relative_path": standalone.relative_to(destination).as_posix(),
                              "bytes": standalone.stat().st_size, "sha256": digest(standalone)})
            if warning:
                database_warnings.append({"relative_path": output.relative_to(destination).as_posix(), **warning})
        except OSError as error:
            errors.append({"source": str(source), "code": error_code(error), "error": str(error)})
        if progress:
            progress("capture", position, len(candidates))
    raw_status = "FAILED" if not files else "PARTIAL" if errors else "COMPLETE"
    record = {"format": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(), "roots": roots,
              "files": files, "errors": errors, "database_warnings": database_warnings, "raw_status": raw_status,
              "file_count": len(files), "bytes": sum(row["bytes"] for row in files)}
    manifest = raw / "BACKUP_MANIFEST.json"
    manifest.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record
