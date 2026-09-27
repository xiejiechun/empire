# P2-23 构建与发布门禁验收

日期：2026-09-27。

## 唯一正式入口

关闭 Empire 后在项目根目录运行：

```powershell
.\verify-release.ps1
```

入口按固定顺序执行：

1. 验证 Python 3.12、项目版本以及 `requirements.lock` 中每个精确版本和 SHA-256；构建工具必须为 PyInstaller 6.22.3。
2. 生成 `build/dependency-report.json`，核对 41 个锁定组件的安装版本、兼容组、范围和核准哈希；执行文档链接、Schema、配置与稳定证据契约，再执行 Ruff、当前严格范围 Mypy 和 pip check。
3. 以 `EMPIRE_INTEGRATION=1` 执行完整测试；集成测试继续使用自身隔离 namespace/source 并只清理测试拥有的数据。
4. 运行隔离容量基线并生成 `build/capacity-report.json`，验证 10/30/50/100 虚拟出口、故障矩阵及 1000 次抖动/取消后的资源回收。
5. 在 100%、125%、150%、200% 四档缩放分别执行基础界面布局渲染。
6. 调用纯打包入口 `build.ps1`；它不再安装构建依赖，也不接受其他 PyInstaller 或 Python 主次版本。
7. 把打包目录移动到带中文和空格、且不具备仓库父目录结构的临时位置，运行 `Empire.exe package-smoke`；再以隔离 `LOCALAPPDATA` 验证首次配置引导和 `check-config`。smoke 只创建 Qt 外壳并截图，不连接 Redis/MySQL、不执行采集、归档、DDL 或业务写入。
8. 生成 `build/release-report.json`，嵌入依赖与容量证据并记录构建清单、EXE SHA-256 和 smoke 截图位置。

任一步失败即停止，不更新为已通过发布。`build.ps1` 保留为门禁内部纯打包能力，不是另一条验收路径。

## 制品身份

每次构建在打包前生成 `build/generated/build_manifest.json` 并嵌入 `empire/build_manifest.json`，字段包括：

- Empire 版本；
- 40 位 Git commit；
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
