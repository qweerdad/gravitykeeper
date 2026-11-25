# Portable Windows GUI and CLI. Windows provides the UCRT and the user
# installs Microsoft's official x64 Visual C++ Redistributable if needed.
import runpy
from pathlib import Path

runtime_filter = runpy.run_path(str(Path(SPECPATH) / "gravitykeeper" / "distribution.py"))
is_microsoft_runtime = runtime_filter["is_microsoft_runtime"]


def without_microsoft_runtime(entries):
    return [entry for entry in entries if not is_microsoft_runtime(entry[0])]

gui = Analysis(["desktop.py"], pathex=[], binaries=[], datas=[], hiddenimports=[],
               hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=["test"], noarchive=False)
cli = Analysis(["console.py"], pathex=[], binaries=[], datas=[], hiddenimports=[],
               hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=["test"], noarchive=False)

gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name="GravityKeeper",
              console=False, upx=False, strip=False)
cli_exe = EXE(PYZ(cli.pure), cli.scripts, [], exclude_binaries=True, name="GravityKeeper-CLI",
              console=True, upx=False, strip=False)

app = COLLECT(gui_exe, cli_exe,
              without_microsoft_runtime(gui.binaries), without_microsoft_runtime(gui.datas),
              without_microsoft_runtime(cli.binaries), without_microsoft_runtime(cli.datas),
              name="GravityKeeper", upx=False, strip=False)
