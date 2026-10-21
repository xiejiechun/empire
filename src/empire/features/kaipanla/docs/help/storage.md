<!-- topic:技术参考|开盘啦存储与维护 -->
<!-- summary:核对开盘啦存储与维护的正式字段、规则和维护边界。 -->
# 开盘啦存储与维护

## 字段与维护

七个 collector/data/ui 插件分别以 `kaipanla_<kind>` 登记，kind 为 trend、auction、volume、trades、entrust、large_order、quote。项目为 `kaipanla-<kind>`（下划线转换连字符），任务在项目后加 `-v1`，数据集为 `kaipanla.<kind>.day@1`，每项目一条 collection_state。

父头字段、明细与块的关联见 [MySQL stock_market_day](help:MySQL%20stock_market_day)，对应八张明细表在“数据库参考 → MySQL”逐项查阅。共享头不共享七个项目完成状态。

显式迁移入口 `scripts/migrate_kaipanla_products.py`，默认只核查，`--apply` 才转换。必须正常关闭 Empire 并排空待归档；每个旧 stock_intraday 证券日拆成 trend 和 auction，在事务内精确读回两条数据、摘要及版本后移除旧行。旧完成状态和计划不继承，旧版拆分入口产生的停用手动配置通过 `scripts/configure_kaipanla_task_defaults.py --apply` 设置推荐默认计划，保留启停、代理和重试；验证转换完成后删除旧表；正式建表不再创建旧表。程序启动不迁移或建表。命令行 `collect-intraday --kind <kind>` 执行独立项目，须先在任务配置启用。

容量实验 `scripts/measure_kaipanla_day.py` 是临时测量入口，十个接口、gzip 文件与正式七项 MySQL 存储范围不同，不能直接把原文容量当 MySQL容量；实验结束删除正文，保留摘要报告。

## 业务结构升级后的操作

日常仍从“数据浏览”查看股票、财报、行业、事件及分时；筛选市场、输入证券代码的方式不变。市场和六位代码从 unified_code 解析，股票来源符号从该身份推导；采集消息中的 node/source_symbol 仍用于来源校验。历史证券不因退出当前股票列表而删除；缺少当前名称时显示代码。来源变更须显式维护，不能切换配置后混存不同来源。

结构升级不改变 payload 科目、金额精度、来源日期语义或摘要。规范内容相同的缓存继续有效；证券代码变更仅沿已有来源别名证明处理，不按名称合并。财报仍缺历史公告日期，升级不使其自动适用于历史选股。


业务代码统一位于features/kaipanla；24个旧模块及调用方同批退役，公共服务不导入本业务表组。schema_contract(tables)读取显式表集合，本业务用唯一business-schema登记选择表组，启动不迁移。复权通过连接内iter_validated_days惰性读取已校验证券日，在调用方既有SQL事务中消费；超过10000个日头、身份/摘要/版本错误均拒绝。

开发有限实采使用scripts/verify_kaipanla.py和共享私有资源生命周期，显式独立13348配置、随机种子与proxy-only。随机至少30只并额外固定原失败证券，逐项核对来源、Redis、统一归档、正式日查询及完整分页；有效私有样本清理后不留生产业务。来源缺口与严格失败保留，不用管线一致代替全部样本成功；中断仅用本地ownership记录按归属清理。此维护入口不修改日常计划。
