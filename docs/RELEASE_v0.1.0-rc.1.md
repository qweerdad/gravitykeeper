# GravityKeeper v0.1.0-rc.1

First public pre-release of GravityKeeper, an unofficial offline backup and recovery tool for locally accessible Google Antigravity conversations.

- Read-only capture of conversation databases and SQLite/WAL groups.
- Markdown and JSON exports with missing-step diagnostics, workspace organization, and local conversation search.
- Windows desktop and CLI, with ZIP packaging and SHA-256 verification.
- Validated on Windows 11 x64 with Antigravity 2.33.0 (product version 2.33.0.0). Other versions and platforms are untested.

The Windows build is unsigned. Fully extract the ZIP and keep _internal beside the EXEs. The package includes Python, uses the Windows UCRT, and requires the [Microsoft Visual C++ v14 x64 runtime](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) obtained from Microsoft. Compare the ZIP against the supplied SHA-256 before use.

GravityKeeper can only use files accessible on the computer. If content or decoding evidence is missing, exports are marked PARTIAL or FAILED. The project is independent of Google and provides no account unlocking, authentication bypass, or online service recovery.

## 简体中文

首次公开预发布。支持本地只读备份、SQLite/WAL 一致性检查、Markdown 和 JSON 导出、按工作区分类、会话搜索和 ZIP 校验。已验证 Windows 11 x64 和 Antigravity 2.33.0 的 SQLite/Brain 布局。软件未签名，运行需要从 Microsoft 官方渠道安装 x64 VC++ v14 运行库。请先核对 ZIP 的 SHA-256。本项目只处理本机可读数据，与 Google 无隶属关系。
