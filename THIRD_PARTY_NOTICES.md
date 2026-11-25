# Third-party notices

GravityKeeper's authored source is under MIT. A portable build also contains the selected Python runtime and its shared libraries. Their licenses continue to apply to those components. See runtime license files in **licenses/** in the distribution.

- CPython is distributed by the Python Software Foundation under the PSF License Agreement and bundled-component terms.
- Tcl/Tk, SQLite, zlib, libffi, OpenSSL and other bundled open-source components retain their respective licensing terms.
- Windows supplies the UCRT. Obtain the x64 Visual C++ v14 runtime directly from Microsoft. The distribution excludes Microsoft runtime DLLs and installers. [Microsoft download information](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) · [Microsoft redistribution terms](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files)
- PyInstaller is used as a build tool. Its application-bundling exception permits distributing the resulting app under its own license, subject to licenses of bundled runtime dependencies.

See the [PyInstaller license and bundling exception](https://pyinstaller.org/en/stable/license.html), the [Python license](https://docs.python.org/3/license.html), and the [source provenance review](docs/source-license-audit.md).
