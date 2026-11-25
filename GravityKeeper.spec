# Portable Windows GUI and CLI with shared runtime files.

gui = Analysis(["desktop.py"], pathex=[], binaries=[], datas=[], hiddenimports=[],
               hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=["test"], noarchive=False)
cli = Analysis(["console.py"], pathex=[], binaries=[], datas=[], hiddenimports=[],
               hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=["test"], noarchive=False)

gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name="GravityKeeper",
              console=False, upx=False, strip=False)
cli_exe = EXE(PYZ(cli.pure), cli.scripts, [], exclude_binaries=True, name="GravityKeeper-CLI",
              console=True, upx=False, strip=False)

app = COLLECT(gui_exe, cli_exe, gui.binaries, gui.datas, cli.binaries, cli.datas,
              name="GravityKeeper", upx=False, strip=False)
