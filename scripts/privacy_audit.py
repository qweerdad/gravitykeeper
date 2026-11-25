"""Gate public source, Git objects and portable contents using static checks."""

import argparse
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parent.parent
PRIVATE_NAME = re.compile(r"(?i)(?:^|/)(?:01_Raw_Backup|02_Conversations_Markdown|03_Conversations_JSON|"
                          r"04_Brain_Artifacts|05_Project_Index|BACKUP_MANIFEST\.json|JOB_REPORT\.json|"
                          r"settings\.json|transcript(?:_full)?\.jsonl|cookies|login data|\.env(?:\..*)?)(?:$|/)")
DB_EXT = re.compile(r"(?i)\.(?:sqlite3?|vscdb|db(?:-wal|-shm|-journal)?|pbtxt|jsonl|pfx|p12|kdbx)$")
PRIVATE_VALUES = (
    re.compile(rb"(?i)(?:[a-z]:[\\/])users[\\/][^\\/\x00\r\n \"']{1,64}[\\/](?:\.gemini|documents|appdata)[\\/]"),
    re.compile(rb"(?i)(?:[a-z]:[\\/])codex[\\/]temp[\\/]"),
    re.compile(rb"(?:AIza[A-Za-z0-9_-]{35}|gh[pousr]_[A-Za-z0-9_]{33,}|sk-[A-Za-z0-9_-]{35,})"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
)
UTF16_ASCII = re.compile(rb"(?:[\x20-\x7e]\x00){4,}")
PORTABLE_ROOT = {"GravityKeeper.exe", "GravityKeeper-CLI.exe", "BUILD_INFO.json",
                 "README.md", "README.zh-CN.md", "PRIVACY.md", "SECURITY.md",
                 "CHANGELOG.md", "LICENSE", "THIRD_PARTY_NOTICES.md"}
PORTABLE_SUBDIRS = {"_internal", "licenses", "docs"}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def inspect(name, data):
    if PRIVATE_NAME.search(name) or DB_EXT.search(name):
        raise ValueError(f"Excluded filename in public payload: {name}")
    if data.startswith(b"SQLite format 3\x00"):
        raise ValueError(f"SQLite database in public payload: {name}")
    # Scan individual UTF-16 strings to avoid joining adjacent binary string tables.
    if any(pattern.search(data) for pattern in PRIVATE_VALUES):
        raise ValueError(f"Potential private value in public payload: {name}")
    for match in UTF16_ASCII.finditer(data):
        if any(pattern.search(match[0][::2]) for pattern in PRIVATE_VALUES):
            raise ValueError(f"Potential private value in public payload: {name}")
    if data.startswith(b"PK\x03\x04") and name.lower().endswith((".zip", ".whl")):
        with ZipFile(io.BytesIO(data)) as inner:
            for info in inner.infolist():
                if not info.is_dir():
                    inspect(f"{name}/{info.filename}", inner.read(info))


def audit_git():
    index = [name.decode("utf-8") for name in git("ls-files", "-z").split(b"\0") if name]
    for name in index:
        inspect(name, git("show", f":{name}"))
        worktree = ROOT / name
        if worktree.is_file():
            inspect(name, worktree.read_bytes())
    commits = git("rev-list", "--all").decode().splitlines()
    seen = set()
    for commit in commits:
        inspect("Git author and message", git("show", "-s", "--format=%an%n%ae%n%cn%n%ce%n%B", commit))
        for evidence in git("ls-tree", "-r", "-z", commit).split(b"\0"):
            if not evidence:
                continue
            header, raw_name = evidence.split(b"\t", 1)
            _, typ, oid = header.decode().split()
            name = raw_name.decode("utf-8")
            if typ != "blob":
                raise ValueError(f"Non-blob Git entry: {name}")
            key = (oid, name)
            if key not in seen:
                inspect(name, git("cat-file", "blob", oid))
                seen.add(key)
    return {"staged_paths": len(index), "historical_commits": len(commits), "checked_history_blobs": len(seen)}


def audit_zip(path):
    with ZipFile(path) as archive:
        entries = [info for info in archive.infolist() if not info.is_dir()]
        seen = set()
        for info in entries:
            rel = PurePosixPath(info.filename)
            top = rel.parts[0]
            if (rel.is_absolute() or ".." in rel.parts or "\\" in info.filename or ":" in info.filename
                    or info.filename.casefold() in seen):
                raise ValueError("Unsafe or duplicate release ZIP path")
            seen.add(info.filename.casefold())
            if (len(rel.parts) == 1 and top not in PORTABLE_ROOT) or (len(rel.parts) > 1 and top not in PORTABLE_SUBDIRS):
                raise ValueError(f"Unexpected release payload: {info.filename}")
            inspect(info.filename, archive.read(info))
        if not {name.casefold() for name in PORTABLE_ROOT} <= seen:
            raise ValueError("Release ZIP is missing required files")
    return {"portable_entries": len(entries), "filename_and_binary_scan": "passed"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--git", action="store_true")
    parser.add_argument("--zip", type=Path)
    args = parser.parse_args()
    result = {}
    if args.git:
        result["git"] = audit_git()
    if args.zip:
        result["zip"] = audit_zip(args.zip)
    if not result:
        parser.error("Pass --git, --zip or both")
    print(json.dumps(result, indent=2))
