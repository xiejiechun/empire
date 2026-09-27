# P3-27 依赖与供应链治理验收

日期：2026-09-27。

## 已建立的正式路径

`requirements.lock` 是唯一依赖锁，目标固定为 Windows x86-64、CPython 3.12。每个包必须使用精确版本并至少包含一个核准 wheel 的 SHA-256；新环境统一用 `pip install --require-hashes -r requirements.lock`，不会在安装时接受同版本的未核准制品。

`scripts/verify_release_environment.py` 统一解析锁文件并拒绝缺少哈希、非 SHA-256、非精确版本和重复包。`scripts/audit_dependencies.py` 复用同一解析入口，核对安装版本并生成 `build/dependency-report.json`。报告列出 41 个 Python 组件的版本、直接/传递范围、兼容组、许可元数据、核准哈希和运行平台；范围不包含 Windows、设备驱动及运行时动态加载的原生组件，因此不把它宣称为整台机器的完整 SBOM。

发布门禁在静态检查之前生成依赖报告；打包只接受与当前锁摘要一致的报告。制品构建清单进一步记录依赖组件数和依赖报告 SHA-256，精简清单随程序目录发布，最终 `build/release-report.json` 嵌入本次报告。`build.ps1` 仍是门禁内部的纯打包能力，不另建第二条依赖解析路径。

## wheel 与安全元数据核验

更新依赖时，先把目标 wheel 下载到临时或 `build` 目录，再显式核对文件名和哈希：

```powershell
python -m pip download --disable-pip-version-check --no-deps --only-binary=:all: `
  --dest build\dependency-wheels -r requirements.lock
python scripts\audit_dependencies.py `
  --wheel-directory build\dependency-wheels `
  --output build\dependency-report.json
```

`--wheel-directory` 要求每个锁定包恰有一个匹配版本且其实际 SHA-256 已被锁文件授权。普通发布不依赖保留大型 wheel 缓存；哈希锁和已安装环境核验始终执行。

需要当前 PyPI 发布元数据时使用独立在线证据入口：

```powershell
python scripts\audit_dependencies.py --output build\dependency-report.json `
  --online-output build\dependency-security-report.json
```

在线报告逐包记录来源 URL、查询时间、PyPI 返回的漏洞项和失败。任一查询失败会把报告标为不完整；PyPI 返回空漏洞列表也不等于包、Qt/加密原生库或操作系统没有漏洞。网络可用性不阻断默认的可重复本地发布门禁，动态在线结果不提交为永久事实。

## 兼容组更新规则

不整体追逐最新版，一次只更新一个兼容组并同步该组的直接和传递依赖：

- Qt：PySide6、Addons、Essentials、shiboken6，专项验证启动、四档 DPI、High Contrast、页面销毁和 EXE smoke。
- validation：pydantic、pydantic-core、annotated-types、typing-inspection，专项验证全部配置模型、序列化及旧字段拒绝。
- database：SQLAlchemy、greenlet、PyMySQL、cryptography/cffi，专项验证事务提交/回滚、取消所有权、连接池关闭、归档重放和只读分页。
- network：httpx/httpcore、anyio、h11、socksio、证书与 IDNA，专项验证 HTTP/HTTPS/SOCKS5H、跳转脱敏、限流、正文/文件边界和取消回收。
- redis：单独成组；跨大版本前核对 Stream、Lua、TIME、Pipeline、连接关闭及 RouterProxy 目录契约。
- build 与 test-quality：分别验证可复现打包、制品内容以及完整质量门禁。

每次更新流程固定为：记录变更依据和安全公告；只修改一个兼容组；重新下载 Windows/CPython 3.12 wheel 并核实哈希；在新隔离虚拟环境用 `--require-hashes` 安装；执行 `verify-release.ps1`；记录版本、报告摘要与回退版本。回退只恢复代码和依赖组，不回滚、清空或删除 Redis/MySQL 业务数据；数据库结构仍只走显式维护入口。

## 本轮证据与边界

本轮没有升级任何依赖。41 个当前版本的 Windows wheel 均通过文件哈希核对，锁解析、缺失/错误哈希、重复包、安装版本和报告生成均有自动测试。最终发布证据以本轮 `build/dependency-report.json`、可选的动态安全元数据报告及完整发布门禁结果为准。
