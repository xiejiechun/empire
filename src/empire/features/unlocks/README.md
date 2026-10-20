# 解禁业务归属：unlocks

`contract.py`是业务身份、字段、规范集合与版本的公开契约；`source.py`解释来源列表/明细或行业目录/月响应；`collector.py`复用共享下载、代理、频控、预取和按序原子入队。`dataset.py`经唯一归档器事务保存，`query.py`提供有界正式查询与数据准备，`ui.py`按需创建页面，`bundle.py`保持原插件、任务、数据集、schema、页面与槽位。

个股以月市场为完整单位，汇总record_key与明细请求group_key分别保留，初始化1990-01至下一自然年12月；列表变化、缺证明及空明细补采，每轮轮换历史月发现明细修订。行业以来源目录及基准日冻结本轮范围，逐月完整行业集合，退出目录的历史保留。入队后继续下载，仅整轮末确认归档；失败不跳过，SQL提交后可重放，成功统一清队。Redis丢失按SQL与来源重建，不承诺丢失消息恢复。

两业务共用唯一`sources/tdx_unlock.py`的PAGE/body/results协议，行业只使用个股公开contract纯规范函数，不引用个股私有source。公共preparation、QueryScope和共享服务保持原路径；无DDL、兼容转发、双登记或启动迁移。来源没有公告可用日，空明细与未知数量如实保留。

操作、单位、关联与限制见[业务说明](../../../../docs/tdx-unlocks.md)。专项分别为`tests/test_tdx_unlocks.py`/`test_tdx_unlock_industries.py`及各自UI和私有归档集成；安全实采/容量入口见`scripts/verify_unlocks.py`、`verify_unlock_industries.py`及两份measure工具。
