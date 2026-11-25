"""Physically extract and launch both portable executables on fictional data."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gravitykeeper.demo import fixture
from gravitykeeper import __version__


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def launch(application, args, base, env):
    process = subprocess.run([str(application), *map(str, args)], cwd=base, env=env,
                             capture_output=True, encoding="utf-8", timeout=120)
    if process.returncode != 0:
        raise RuntimeError(f"{application.name} exited with {process.returncode}: {process.stderr}")
    return process.stdout


def smoke(path, cli_only=False):
    checksum = path.with_name(path.name + ".sha256")
    if checksum.read_text(encoding="utf-8").strip() != f"{digest(path)}  {path.name}":
        raise RuntimeError("Published ZIP hash mismatch")
    with TemporaryDirectory(prefix=".gk-test-", dir=ROOT) as work:
        temp = Path(work)
        folder = temp / "Portable"
        folder.mkdir()
        with ZipFile(path) as bundle:
            names = bundle.namelist()
            if len(names) != len(set(name.casefold() for name in names)):
                raise RuntimeError("Duplicate ZIP member")
            for name in names:
                relative = PurePosixPath(name)
                if relative.is_absolute() or ".." in relative.parts or ":" in name or "\\" in name:
                    raise RuntimeError("Unsafe ZIP member")
            bundle.extractall(folder)
            for name in names:
                with bundle.open(name) as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != digest(folder / name):
                        raise RuntimeError(f"Extraction mismatch: {name}")
        env = {key: value for key, value in os.environ.items()
               if key.upper() not in {"PYTHONHOME", "PYTHONPATH", "PATH", "TCL_LIBRARY", "TK_LIBRARY"}}
        windows = Path(os.environ["SystemRoot"])
        env["PATH"] = str(windows / "System32") + os.pathsep + str(windows)
        command = folder / "GravityKeeper-CLI.exe"
        gui = folder / "GravityKeeper.exe"
        version = launch(command, ["--version"], folder, env).strip()
        if version != __version__:
            raise RuntimeError(f"Packaged CLI version mismatch: {version}")
        data = fixture(temp / "CLI profile")
        snapshot = temp / "CLI snapshot"
        raw = launch(command, ["run", snapshot, "--source", data], folder, env)
        cli = json.loads(raw)
        if cli["raw"] != "COMPLETE" or cli["export"] != "COMPLETE":
            raise RuntimeError("Packaged CLI did not complete its synthetic export")
        check = json.loads(launch(command, ["verify", snapshot], folder, env))
        if check["files"] <= 0:
            raise RuntimeError("Packaged CLI did not verify its snapshot")
        gui_status = None
        if not cli_only:
            report = temp / "GUI-evidence.json"
            launch(gui, ["--smoke-report", report], folder, env)
            gui_status = json.loads(report.read_text(encoding="utf-8"))
            if (gui_status.get("backup") != "COMPLETE" or gui_status.get("export") != "COMPLETE"
                    or gui_status.get("search_results") != 1 or gui_status.get("verified_zip_entries", 0) <= 0):
                raise RuntimeError(f"Unexpected packaged GUI smoke result: {gui_status}")
        return {"release_zip_entries": len(names), "cli_version": version, "cli": cli["sessions"],
                "cli_verified_files": check["files"], "gui": gui_status,
                "path_environment": "Windows system directories only"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("zip", type=Path)
    parser.add_argument("--cli-only", action="store_true", help="Extract, hash-check and test only the CLI")
    args = parser.parse_args()
    print(json.dumps(smoke(args.zip.resolve(), args.cli_only), ensure_ascii=False, indent=2))
