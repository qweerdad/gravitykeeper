"""Build, collect notices, and seal the Windows x64 portable distribution."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import runpy
import shutil
import sys
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent.parent
PORTABLE_DOCS = ("README.md", "README.zh-CN.md", "LICENSE", "THIRD_PARTY_NOTICES.md",
                 "PRIVACY.md", "SECURITY.md", "CHANGELOG.md")
RUNTIME_PACKAGES = {"python", "tk", "tcl", "sqlite", "libffi", "zlib", "libzlib", "openssl",
                    "bzip2", "xz", "xz-tools", "liblzma", "zlib-ng"}
is_microsoft_runtime = runpy.run_path(str(ROOT / "gravitykeeper" / "distribution.py"))["is_microsoft_runtime"]


def collect_licenses(portable):
    prefix = Path(sys.base_prefix)
    dest = portable / "licenses"
    dest.mkdir(exist_ok=True)
    for candidate in (prefix / "LICENSE.txt", prefix / "LICENSE_PYTHON.txt"):
        if candidate.is_file():
            shutil.copyfile(candidate, dest / "CPython.txt")
            break
    else:
        raise SystemExit("Python runtime redistribution license was not found")
    if (prefix / "conda-meta").is_dir():
        for document in sorted((prefix / "conda-meta").glob("*.json")):
            record = json.loads(document.read_text(encoding="utf-8"))
            name = record.get("name")
            link = record.get("link") or {}
            cache = link.get("source")
            if name not in RUNTIME_PACKAGES or not cache:
                continue
            source = Path(cache) / "info" / "licenses"
            if source.is_dir():
                for file in sorted(source.rglob("*")):
                    if file.is_file():
                        target = dest / name / file.relative_to(source)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(file, target)
    for name in ("license.terms", "license.txt"):
        for family in ("tcl", "tk"):
            candidates = [prefix / "tcl" / f"{family}8.6" / name,
                          prefix / "Library" / "lib" / f"{family}8.6" / name]
            for candidate in candidates:
                if candidate.is_file():
                    shutil.copyfile(candidate, dest / f"{family}-{name}")
                    break


def deliver(portable, output):
    excluded = [p.name for p in portable.rglob("*") if p.is_file() and is_microsoft_runtime(p.name)]
    if excluded:
        raise SystemExit("Microsoft runtime files remain in the bundle: " + ", ".join(excluded))
    for name in PORTABLE_DOCS:
        shutil.copy2(ROOT / name, portable / name)
    docs = portable / "docs"
    (docs / "screenshots").mkdir(parents=True, exist_ok=True)
    for name in ("testing.md", "source-license-audit.md"):
        shutil.copy2(ROOT / "docs" / name, docs / name)
    for source in sorted((ROOT / "docs" / "screenshots").glob("*.jpg")):
        shutil.copy2(source, docs / "screenshots" / source.name)
    collect_licenses(portable)
    metadata = {"python": platform.python_version(), "architecture": platform.machine(),
                "builder": "PyInstaller 6.17.0", "variant": "Windows portable directory",
                "requires": "Windows UCRT and Microsoft Visual C++ v14 Redistributable (x64)"}
    (portable / "BUILD_INFO.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    version = runpy.run_path(str(ROOT / "gravitykeeper" / "__init__.py"))["__version__"]
    target = output / f"GravityKeeper-{version}-windows-x64.zip"
    checksum = target.with_name(target.name + ".sha256")
    with ZipFile(target, "x", ZIP_DEFLATED, compresslevel=6) as archive:
        for file in sorted(portable.rglob("*")):
            if file.is_file():
                archive.write(file, file.relative_to(portable).as_posix())
    with target.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    with checksum.open("x", encoding="utf-8") as stream:
        stream.write(f"{digest}  {target.name}\n")
    print(target)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "release")
    parser.add_argument("--build-dependencies", type=Path)
    parser.add_argument("--compile-only", action="store_true")
    parser.add_argument("--package-only", action="store_true")
    args = parser.parse_args()
    if os.name != "nt" or platform.machine().upper() not in {"AMD64", "X86_64"}:
        raise SystemExit("The portable build requires a Windows x64 build host")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    portable = output / "GravityKeeper"
    if not args.package_only:
        if portable.exists():
            raise SystemExit("Use a fresh output directory to compile")
        if args.build_dependencies:
            sys.path.insert(0, str(args.build_dependencies.resolve()))
        # The Conda Python runtime locates shared libraries here.
        library = Path(sys.base_prefix) / "Library" / "bin"
        if library.is_dir():
            os.environ["PATH"] = str(library) + os.pathsep + os.environ["PATH"]
        import PyInstaller.__main__
        os.chdir(ROOT)
        PyInstaller.__main__.run(["--noconfirm", "--distpath", str(output), "--workpath",
                                  str(output / "build"), str(ROOT / "GravityKeeper.spec")])
    if not args.compile_only:
        deliver(portable, output)


if __name__ == "__main__":
    main()
