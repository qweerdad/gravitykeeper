# Testing and compatibility

## Run locally

~~~powershell
python -B -m unittest discover -s tests -v
python -B desktop.py --demo
python -B scripts/privacy_audit.py --git
python -B scripts/privacy_audit.py --zip release/GravityKeeper-0.1.0rc1-windows-x64.zip
python -B scripts/smoke_package.py release/GravityKeeper-0.1.0rc1-windows-x64.zip
~~~

All repository fixtures are generated fiction. The suite covers a live, open SQLite WAL with a committed row available only through WAL replay, a real Windows exclusive file handle, and a simulated insufficient-space response. It also checks separate raw/export verdicts, unrecognized database bytes, missing full transcripts, salvage from chunks, validated Protobuf error controls, workspace/parent relationships, Unicode paths and search, long transcripts, media and artifact links, collision prevention, source byte preservation, ZIP extraction, and hash mismatch rejection.

The portable smoke test extracts the Release ZIP, compares every extracted file to its archive member, and starts both EXEs. It exercises capture, Markdown/JSON export, GUI search, ZIP creation and integrity verification. The process PATH is restricted to Windows system directories.

## Validation scope

- Target candidate is Windows 11 x64 and the Antigravity 2.33.0 SQLite/Brain layout. Windows 10, macOS, Linux, ARM64 and other Antigravity versions are outside the validated matrix.
- A read-only probe of a real installation and an export against an isolated copy of real data were treated as separate acceptance checks. The public repository includes neither the input nor the resulting exports.
- A hosted GitHub workflow is provided. Local candidate results are separate from any future GitHub Actions result.
- The portable bundle is unsigned. Its SHA-256 sidecar records the delivered bytes.
