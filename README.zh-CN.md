# GravityKeeper

[English](README.md)

**只要 Antigravity 会话仍保存在电脑上，就有机会离线备份和导出。** GravityKeeper 可用于无法登录、电脑迁移或长期归档。它是与 Google 无隶属或合作关系的非官方社区工具，免费开源，不处理账号解封、在线服务恢复或会话写回。

可运行 **GravityKeeper.exe --demo**，从合成数据体验实际软件界面。源码版对应命令为 **python desktop.py --demo**。

## 使用方法

1. 下载 Windows x64 便携 ZIP 及 SHA-256 文件，核对哈希后完整解压。
2. 启动 **GravityKeeper.exe**。保持 _internal 目录与两份 EXE 在同一目录。便携版无需预装 Python。
3. 在 **设置** 检查源目录和输出位置。选择 **完整备份** 可一次生成原始副本、Markdown、JSON、项目索引和本地附件。磁盘空间紧张时可先选择 **仅备份原始数据**。
4. 从 **历史会话** 读取并搜索导出结果，或在 **备份管理** 和 **完整性检查** 打包、核验或打开输出目录。**仅导出会话** 可用于尚未导出的已校验原始快照。

~~~powershell
Get-FileHash -Algorithm SHA256 .\GravityKeeper-0.1.0rc1-windows-x64.zip
.\GravityKeeper-CLI.exe discover
.\GravityKeeper-CLI.exe run ".\演示快照" --progress
.\GravityKeeper-CLI.exe search ".\演示快照" "城市博物馆"
.\GravityKeeper-CLI.exe zip ".\演示快照" ".\演示快照.zip"
.\GravityKeeper-CLI.exe verify ".\演示快照.zip"
~~~

定期备份可由当前 Windows 用户用任务计划程序调用 CLI，每次指定新目录。退出码 0 表示所执行操作通过，2 表示操作或校验失败，3 表示存有可用结果但捕获或导出不完整。使用源码时可运行 **python desktop.py** 或 **python -m gravitykeeper**。

## 支持范围

| 项目 | 本候选版验证 |
| --- | --- |
| Windows 11 x64 | 已执行本机候选版验收，源码与便携程序的测试范围见验收报告 |
| Antigravity 2.33.0，产品版本 2.33.0.0 | 已核验本机探测及 SQLite / Brain 布局 |
| Windows 10、ARM64、macOS、Linux | 未测试 |
| 其他 Antigravity 版本 | 未测试，可能仅能发现和复制原始文件 |
| 没有可读日志的旧版不透明 .pb | 保留原始字节，会话导出报告 FAILED |
| 源码运行 | Python 3.11+，GUI 需要 Tk，运行阶段无额外 Python 包 |

## 判定与故障排查

- **COMPLETE** 表示本次本机资料和核验步骤支持完整结论。**PARTIAL** 表示可用内容已保存，仍有缺项或证据不足。**FAILED** 表示该阶段失败或无可核验的会话正文。原始复制与会话导出在 JOB_REPORT.json 中分别判定，原因及步骤序号见 SESSION_VERIFICATION.json。
- **锁定或持续写入**。原始数据库仅用文件系统读取，SQLite 只打开隔离副本。若无法稳定复制，查看失败记录并在写入较少时换一个新目标重试。
- **空间不足**。改用有余量的磁盘或先备份原始数据。ZIP 需存到快照目录外。
- **找不到软件或工作区**。查看设置中的数据目录。版本来自常见 Windows 安装路径，工作区依赖可读的本地摘要索引。
- **便携版打不开**。确认已解压整个 ZIP，_internal 目录仍在原处。候选包尚未做代码签名。

详见[英文说明](README.md)、[隐私边界](PRIVACY.md)、[测试说明](docs/testing.md)和 [MIT 许可证](LICENSE)。
