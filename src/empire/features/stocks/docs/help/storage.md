<!-- topic:技术参考|股票表字段（stock） -->
<!-- summary:股票表字段迁至独立对象页。 -->
# 股票表字段（stock）

## 发布与查询

[MySQL stock](help:MySQL%20stock) 保存唯一当前目录；[MySQL collection_state](help:MySQL%20collection_state) 保存最后 SQL 确认及 publication。股票页面更新时刻只代表最后实际内容变化，不等于最近采集核验。

## 运行核验

`<namespace>:stocks:committed:<source>` 保存最近成功核验，字段和恢复限制见 [Redis stocks-committed](help:Redis%20stocks-committed)。相同内容不执行业务 DML，可信摘要命中免 MySQL；成功确认后公共归档器清队。

## 时间

SQL `DATETIME(6)` 按北京时间保存。[股票列表](help:股票列表) 负责日常操作与业务范围。
