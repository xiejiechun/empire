# 构建与发布门禁

2026-10-19：发布流程加固。实际通过的发布身份与结果以本次 evidence 为准，本文说明现行执行与恢复方式。

## 唯一正式入口

关闭 Empire 后在项目根目录运行：

```powershell
.\verify-release.ps1
```

`verify-release.ps1` 与直接执行的 `build.ps1` 都调用 `scripts/release.py`，没有可绕过测试的重复打包入口。入口持有同一个操作系统独占文件句柄；从恢复检查直到最终切换始终保有发布所有权，子进程未退出时也不能由第二发布接管。锁文件不能手动删除。

入口按固定顺序执行：

1. 验证 Python 3.12、项目版本以及 `requirements.lock` 中每个精确版本和 SHA-256；构建工具必须为 PyInstaller 6.22.3。
2. 冻结源输入清单、Git 身份并生成 `build/dependency-report.json`；核对锁定组件的安装版本、兼容组、范围和核准哈希，组件数量由清单计算。执行文档、数据库设计、架构依赖检查，再执行 Ruff、当前严格范围 Mypy 和 pip check。
3. 以 `EMPIRE_INTEGRATION=1` 执行完整测试；每次发布使用独立测试临时目录，每个集成用例使用私有数据库及 Redis 命名空间，只清理自己拥有的数据。测试结果绑定源摘要，失败或旧摘要不能形成通过证据。
4. 运行隔离容量基线，在本次 `build/releases/<标识>/` 保存容量报告，验证虚拟出口、故障矩阵及抖动/取消后的资源回收。
5. 在 100%、125%、150%、200% 四档缩放分别执行基础界面布局渲染。
6. 在本次拥有的 staging 目录调用 PyInstaller，正式 `dist/Empire` 不作为打包输出；核对包内构建清单、依赖报告和 preparation 测试证据与当前输出完全一致。
7. 暂存包位于中文含空格路径，从另一工作目录执行 `Empire.exe package-smoke`、首次配置引导及 `check-config`；只删除 smoke 生成的空白模板。使用隔离 LOCALAPPDATA，不接触正式配置。smoke 不连接 Redis/MySQL、不执行采集、归档、DDL 或业务写入。
8. 再次确认程序已正常退出、源输入和生成证据未改变；逐字节复制现有程序配置到候选包，使用有持久记录的目录切换发布。最终核对后，`publication.json` 才标为 committed/passed，`build/release-report.json` 是其便捷副本。

任一步失败即停止；切换前旧程序保持原位，切换失败按本次记录恢复旧包及配置。旧包保留在本次 `previous/Empire`，不自动删除。包含真实配置的旧包、候选包和本地备份都不能作为公共分发资源。

## 输入与生成证据

完整发布输入涵盖源码、测试、维护及发布脚本、SQL、示例配置、依赖、源资源和文档；真实 `config.toml` 单独保护，构建输出不进入源输入清单。每一步前后核对源输入、Git HEAD 以及已形成的证据；生成的测试、依赖、构建、容量等输出独立计算摘要，再绑定源身份，避免摘要自引用。源内容相同不代表已完成业务实采，报告也不把真实桌面操作自动标成通过。

`scripts/preparation_evidence.py package` 在缺少证据、测试失败或源码不匹配时直接失败。其业务摘要覆盖程序正文、JSON 与图片等资源；纯开发 docs 与构建生成输出属于整体发布身份，不作为业务摘要的自引用输入。

## 发布中断与恢复

正常关闭 Empire 后执行 `verify-release.ps1 -Recover`，仅检查本仓库 `build/releases/` 中尚未完成的切换记录，恢复已核实的原包。文件夹身份不符、原包被改、目标被占用或记录不完整时明确失败，保留现场，不强杀进程、不覆盖未知目录。随后重新运行完整门禁才能发布新代码。已提交成功的发布不由此命令回退；其旧包用于明确的维护恢复。

## 制品身份

每次构建在打包前生成 `build/generated/build_manifest.json` 并嵌入 `empire/build_manifest.json`，字段包括：

- Empire 版本；
- 40 位 Git commit；
- 本次 release ID 和完整源输入摘要；
- 构建时工作区是否含未提交修改；
- `requirements.lock` SHA-256；
- 依赖组件数与 `dependency-report.json` SHA-256；
- UTC 构建时间；
- Python 与 PyInstaller 版本。

“系统设置 → 运行状态”直接显示版本、短 commit 和工作区状态，完整构建时间、解释器、构建器与依赖摘要放在提示中。采集错误/归档运行记录也使用同一构建身份，不再只显示无法区分制品的包版本。开发源码运行明确显示为开发环境。

## 依赖与平台边界

`requires-python` 已收紧为 `>=3.12,<3.13`。PyInstaller 及 altgraph、pefile、hooks、pywin32-ctypes、setuptools 已进入带 Windows wheel SHA-256 的精确锁文件，新环境按 README 使用 `--require-hashes` 安装锁文件和项目本身，再运行唯一门禁。兼容分组、wheel 核验、在线安全元数据边界和回退要求见 [依赖与供应链治理](dependency-governance-review.md)。

本门禁是 Windows 本地发布路径，不等于远端 CI、代码签名或安装器。当前没有自动发布到外部，也不自动修改生产数据库。搬移验证、只读资源和用户配置路径见 [独立分发与配置路径验收](portable-distribution-review.md)。工作区有修改时仍允许生成用于本地验证的制品，但清单明确标记 `dirty`，不能把它误认为干净提交构建。

可版本化的脱敏门禁摘要与本机详细 build 制品分工见 [文档契约与稳定证据验收](documentation-governance-review.md)。文档断链、旧配置被写成当前路径、正式表遗漏、容量默认值漂移或 Redis/MySQL 持久化描述冲突都会在打包前失败。
