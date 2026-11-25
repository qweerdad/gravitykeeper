# Source provenance and license review

GravityKeeper's filesystem capture, wire helpers, and export reconciliation were developed for a prior local recovery. This candidate adapts those locally authored modules and adds new packaging, reporting, catalogue, desktop and test code. No third-party Antigravity exporter files, translated code, fixtures, assets, API client, or extracted Antigravity software are included. The data layout and the small wire decoder are based on local file observations and synthetic format controls.

Public projects were evaluated as references for the general problem and to confirm licensing boundaries.

| Reference | Review disposition |
| --- | --- |
| [AI Chat Vault](https://github.com/imperfec-t/ai-chat-vault/blob/main/LICENSE) | MIT with a separate upstream copyright notice in its license. No source or assets taken. Its client repair and write-back paths are outside GravityKeeper. |
| [Antigravity Conversation Exporter](https://github.com/mehdawimohamed/antigravity-conversation-exporter) | No license grant was confirmed through the repository license endpoint. No source, assets or wording taken. |
| [google-antigravity-export](https://github.com/winters27/google-antigravity-export/blob/main/LICENSE) | PolyForm Noncommercial 1.0.0. Code under that grant must not be incorporated into this MIT candidate without an additional compatible grant. No source or assets taken. |

MIT applies to the authored project. PyInstaller is a build dependency. Its executable-bundling exception does not impose GPL terms on the authored application. The bundled Python runtime, Tcl/Tk and other shared libraries retain their own terms. The portable package includes the corresponding runtime notices. [PyInstaller licensing](https://pyinstaller.org/en/stable/license.html) · [CPython licensing](https://docs.python.org/3/license.html)

The release archive excludes Microsoft's runtime files and installers because a separate redistribution entitlement was not established. On the supported Windows platform, use the operating system's UCRT and obtain the Visual C++ v14 x64 Redistributable directly from Microsoft. The build and release audit enforce the exclusion. [Microsoft redistribution guidance and REDIST references](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files) · [Official Microsoft downloads](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)

If third-party implementation code is proposed later, identify the original file and pinned revision. Review the explicit grant and attribution terms before including it. If permission is absent or incompatible, leave it out or obtain a compatible license from the rightsholder.
