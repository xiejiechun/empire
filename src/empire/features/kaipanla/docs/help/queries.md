<!-- topic:技术参考|行情事实字段与查询 -->
<!-- summary:核对行情事实字段与查询的正式字段、规则和维护边界。 -->
# 行情事实字段与查询

## 字段与维护

日常从“数据浏览→数据目录”打开所需开盘啦页面，输入证券和交易日查询。序列每次最多200个来源点，上一页/下一页在数据库按顺序取页，保留同分钟竞价和同秒分笔；若该日发生来源修订，旧页游标明确失效，点击查询重新开始。盘口仍只读取同日独立分时，不要求其他项目全部完成。已保存任务计划不受结构升级影响，数据持久保存在MySQL。

stock_market_day为每项证券日业务头，保存身份、上市关联、业务摘要、版本、点数、键集合摘要和校验契约；不再保存整份payload。普通补缺只查当前证明和生命周期，详细数据准备另核验实际明细。四种分钟明细为stock_intraday_trend、stock_minute_volume、stock_minute_entrust、stock_large_order_trend；竞价stock_opening_auction按来源序号；日摘要stock_daily_quote与20档stock_daily_quote_level分别保存指标和价量。stock_intraday_trade_block每200笔保存一个类型化压缩块，单块最多12400字节解码正文，包含原时刻和7个数值，不是HTTP原文，也不表示交易所完整逐笔流水。扩展JSON只保留有白名单的日统计、别名证明和来源元数据，每字段16KiB上限。

旧七项JSON布局须正常关闭Empire、待归档为0，通过scripts/migrate_market_storage.py的preflight、migrate、verify显式升级，默认项目根config.toml、--config覆盖。日志支持status/resume；影子数据逐单元及全集核验后切换。启动不迁移，结构不符明确报错。旧恢复副本不作为应用读写路径；恢复运行有业务变化后禁止回退旧快照。数据库结构与发布验收记录和实际来源缺口分别报告，34个历史样本缺口不能通过改表消除。


### 对象字典入口

分钟事实、竞价、分笔块、日摘要和档位各有独立数据库条目，字段定义以这些条目为准：[数据库职责与查阅](help:数据库职责与查阅)、[MySQL stock_market_day](help:MySQL%20stock_market_day)、[MySQL stock_intraday_trade_block](help:MySQL%20stock_intraday_trade_block)、[MySQL stock_daily_quote](help:MySQL%20stock_daily_quote)。

分笔技术查询支持HH:MM:SS起止时段与版本绑定游标，保留同秒跨块多笔；日摘要分析查询按字段投影与日期/证券键有界分页。页面仍用当前页查询，详细整日与数据准备会完整核验，耗时更高。有限样本容量结果不能证明全市场多年存储可用，分笔块不能直接在SQL逐笔聚合；扩展范围前先核对磁盘与容量预算。

数据页标明实际结果证券和日期；新输入草稿与旧结果分开，查询失败保留旧结果时标明原范围。盘口可选数值的显式空值、零与缺字段分别保留，必需字段为空不归档。来源修订只提交实际变化的列，同内容不写业务表。
