# 北交所证券代码映射

本包拥有官方完整换码表的业务契约、解析及归档声明。只有显式维护命令，没有定时采集或独立页面。

- 改字段与集合校验：`contract.py`；URL、1000项上限和validate只有一个权威。
- 改网页解析：`source.py`；表头、序号、表结束与官方注释共同证明完整响应。
- 改归档：`dataset.py`；一对一映射冲突整事务拒绝，保留历史、修订与旧版本保护。
- 改贡献：`bundle.py`；原dataset槽位2000及显式维护发布者身份不变。
- 正式入口：`scripts/import_bse_code_mapping.py`；共享下载、代理、入队及统一归档，不在启动时导入。
- 查验证：`tests/test_bse_code_mapping.py`、`tests/integration/test_security_alias_archive.py`；安全容量与实采分别使用`measure_bse_capacity.py`及`verify_bse_code_mapping.py`。

初始化与后续均一次下载完整官方表；SQL成功或确认无需写入并清队才完成。失败留原数据和未确认消息，Redis丢失重新下载；网页移除关系不删除SQL历史。本表不是当前北交所名单，不推算未公布旧代码、生效日或ISIN。正式查询是有界SQL，操作、生命周期和字典见[业务说明](../../../../docs/bse-code-mapping.md)。

## 程序内说明维护

离线帮助的权威正文位于本包 [docs/help/mysql-security-code-alias.md](docs/help/mysql-security-code-alias.md) 及同目录其他完整主题；[来源清单](../../documentation/help-index.json) 统一声明阅读顺序。修改片段后在发布冻结前显式执行 scripts/documentation_build.py generate，再完成文档审阅与相关验证。原有来源指南继续解释业务契约；生成聚合物不手工维护。
