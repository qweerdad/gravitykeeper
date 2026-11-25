"""Snapshot manifests and offline ZIP/hash verification."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

from .capture import digest, safe_entry
from .errors import StorageError, ensure_space
from .paths import isolated_directory


SUMS = "SHA256SUMS.txt"
RAW_MANIFEST = "01_Raw_Backup/BACKUP_MANIFEST.json"
HASH = re.compile(r"^[a-f0-9]{64}$")


def relative_name(name):
    if any(char in name for char in ("\r", "\n", "\\", ":")):
        raise StorageError("unsafe_archive_entry", f"Invalid archive filename: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts or path.as_posix() != name:
        raise StorageError("unsafe_archive_entry", f"Invalid archive filename: {name!r}")
    return name


def files(root):
    for folder, subfolders, names in os.walk(root, followlinks=False):
        base = Path(folder)
        for name in [*subfolders, *names]:
            if not safe_entry(base / name):
                raise StorageError("unsafe_archive_entry", f"Link or reparse point: {base / name}")
        for name in names:
            path = base / name
            yield relative_name(path.relative_to(root).as_posix()), path


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def checksum_rows(text):
    values = {}
    folded = set()
    for line in text.splitlines():
        expected, separator, name = line.partition("  ")
        checked = relative_name(name) if separator else ""
        if not HASH.fullmatch(expected) or not checked or checked == SUMS or checked.casefold() in folded:
            raise StorageError("invalid_checksums", "Invalid or duplicate checksum entry")
        values[checked] = expected
        folded.add(checked.casefold())
    return values


def seal(root, progress=None):
    selected = sorted((name, path) for name, path in files(root) if name != SUMS)
    hashes = []
    for i, (name, path) in enumerate(selected, 1):
        hashes.append(f"{digest(path)}  {name}")
        if progress:
            progress("hash", i, len(selected))
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=root, delete=False) as pending:
        path = Path(pending.name)
        pending.write("\n".join(hashes) + "\n")
    path.replace(root / SUMS)


def verify_manifest(manifest, hash_map):
    if manifest.get("format") != 1 or not isinstance(manifest.get("files"), list):
        raise StorageError("unsupported_manifest", "Unknown backup manifest format")
    if manifest.get("file_count") != len(manifest["files"]):
        raise StorageError("invalid_manifest", "Raw manifest count does not match")
    seen = set()
    for item in manifest["files"]:
        name = relative_name(item["relative_path"])
        if not name.startswith("01_Raw_Backup/") or name in seen or hash_map.get(name) != item["sha256"]:
            raise StorageError("checksum_mismatch", f"Inconsistent raw manifest entry: {name}")
        seen.add(name)
    if {name for name in hash_map if name.startswith("01_Raw_Backup/") and name != RAW_MANIFEST} != seen:
        raise StorageError("invalid_manifest", "Raw manifest does not cover all raw backups")


def verify_snapshot(root, progress=None):
    selected = dict(files(root))
    if SUMS not in selected or RAW_MANIFEST not in selected:
        raise StorageError("snapshot_missing", "Select a snapshot with a manifest and SHA256SUMS.txt")
    checks = checksum_rows(selected[SUMS].read_text(encoding="utf-8"))
    if checks.keys() != (selected.keys() - {SUMS}):
        raise StorageError("checksum_mismatch", "Snapshot files differ from the checksum list")
    for i, (name, expected) in enumerate(checks.items(), 1):
        if digest(selected[name]) != expected:
            raise StorageError("checksum_mismatch", f"SHA-256 mismatch: {name}")
        if progress:
            progress("verify", i, len(checks))
    manifest = load_json(selected[RAW_MANIFEST])
    verify_manifest(manifest, checks)
    return {"files": len(checks), "manifest": manifest}


def verify_zip(path, progress=None):
    sidecar = path.with_name(path.name + ".sha256")
    outer_hash = digest(path)
    if sidecar.is_file() and sidecar.read_text(encoding="utf-8").strip() != f"{outer_hash}  {path.name}":
        raise StorageError("checksum_mismatch", "ZIP SHA-256 sidecar mismatch")
    with ZipFile(path) as archive:
        names = [relative_name(info.filename) for info in archive.infolist()]
        if len(names) != len({name.casefold() for name in names}):
            raise StorageError("unsafe_archive_entry", "Duplicate ZIP entry")
        if SUMS not in names or RAW_MANIFEST not in names:
            raise StorageError("snapshot_missing", "ZIP is not a supported GravityKeeper snapshot")
        checks = checksum_rows(archive.read(SUMS).decode("utf-8"))
        if checks.keys() != (set(names) - {SUMS}):
            raise StorageError("checksum_mismatch", "ZIP files differ from the checksum list")
        verify_manifest(json.loads(archive.read(RAW_MANIFEST)), checks)
        for i, (name, expected) in enumerate(checks.items(), 1):
            with archive.open(name) as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                    raise StorageError("checksum_mismatch", f"ZIP member SHA-256 mismatch: {name}")
            if progress:
                progress("verify_zip", i, len(checks))
    return {"files": len(checks), "sha256": outer_hash, "sidecar_present": sidecar.is_file()}


def package_snapshot(root, destination, progress=None):
    root, destination = root.resolve(), destination.resolve()
    sidecar = destination.with_name(destination.name + ".sha256")
    if destination.is_relative_to(root):
        raise StorageError("unsafe_destination", "Store the ZIP outside the snapshot folder")
    if destination.exists() or sidecar.exists():
        raise StorageError("destination_exists", "The ZIP destination already exists")
    if destination.suffix.lower() != ".zip":
        raise StorageError("unsupported_format", "Choose a .zip destination")
    verify_snapshot(root, progress)
    selected = sorted(files(root))
    size = sum(path.stat().st_size for _, path in selected)
    ensure_space(destination, size + max(size // 20, 1024 * 1024))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with isolated_directory(destination.parent, "zip_") as temporary:
        staged = temporary / "snapshot.zip"
        with ZipFile(staged, "x", compression=ZIP_DEFLATED, compresslevel=4) as archive:
            for i, (name, source) in enumerate(selected, 1):
                archive.write(source, name)
                if progress:
                    progress("zip", i, len(selected))
        result = verify_zip(staged, progress)
        # A hard link is atomic and fails if another process reserved the name.
        if os.name == "nt":
            staged.rename(destination)
        else:
            os.link(staged, destination)
        with sidecar.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(f"{result['sha256']}  {destination.name}\n")
    return {**result, "path": str(destination), "sidecar_present": True}
