# 同花顺财报三表

本包拥有利润表、资产负债表和现金流量表的来源矩阵、消息契约、归档、查询、数据准备与页面。入口声明位于 `bundle.py`，由 `features/builtin.py` 显式装配；三组原插件、任务、数据集、页面身份及非连续顺序保持不变，不增加运行时插件种类。

| 修改目的 | 权威入口 |
| --- | --- |
| 来源字段、日期、金额精度和集合 | `contract.py` 的 parse/validate_rows；quality.py 单列金额质量 |
| 请求、按序断点、整轮完成 | `collector.py`，共享下载器/代理/频控及 unit_prefetch |
| schema 2 紧凑矩阵消息 | `wire.py`；滚动集合 chain 属于 contract.py |
| SQL 比较、修订与证明 | `dataset.py`，统一归档器及 fingerprint 服务 |
| 正式浏览与准备核查 | `query.py` / `audit.py`；公共 preparation 契约仍在 contracts |
| 页面、科目矩阵与摘要 | `ui.py` / `statement_matrix.py` / `statement_preview.py`；布局资源 statement_layouts.json |
| 专项与实采验证 | tests/test_ths_statements.py、tests/integration/test_financial_archive.py、scripts/verify_ths_statements.py |

每证券每表请求一次完整历史 JSON，按冻结的当前股票池顺序校验入队；下载与归档独立推进，整轮末确认归档。普通续采保留断点，池集合改变则新轮从首证券开始，Redis 丢失后全池重查。已有历史不删除，不变业务不写，迟到旧响应不覆盖，SQL 提交后重放及成功清队由公共路径执行。

报告期不是公告日期；来源早期、非季末报告、缺值及金额舍入均原样保留，不生成单季/TTM，不承诺历史公告前选股可用。来源质量与集合完整性分别判断。业务说明及历史实采范围见 [三表说明](../../../../docs/ths-financial-statements.md)，存储字段以 [数据库参考](../../../../docs/database-reference.md) 为准。

安全实采复用 scripts/source_verification.py 和 source_test_storage.py：正式库仅只读股票池/共享设置与实例身份，写入仅在核实不同 server_uuid 的13348私有UUID库及带owner的Redis前缀。三表逐项核对日期集合、内容、质量、SQL manifest、正式audit及pending=0；固定历史反例另加随机30股。报告的采集完整不代表金额质量或历史信号用途通过，不变更用户日常网络配置。

## 程序内说明维护

离线帮助的权威正文位于本包 [docs/help/overview.md](docs/help/overview.md) 及同目录其他完整主题；[来源清单](../../documentation/help-index.json) 统一声明阅读顺序。修改片段后在发布冻结前显式执行 scripts/documentation_build.py generate，再完成文档审阅与相关验证。原有来源指南继续解释业务契约；生成聚合物不手工维护。
