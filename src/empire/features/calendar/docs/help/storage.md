<!-- topic:技术参考|日历表字段（trade_calendar） -->
<!-- summary:日历字段迁至独立对象页。 -->
# 日历表字段（trade_calendar）

## 月份校验

[MySQL trade_calendar](help:MySQL%20trade_calendar) 为唯一字段说明。整月包含交易与休市日期，缺少、重复、跨月或无效标记拒绝归档；不推断缺日为休市。

## 时效证据

SQL 月份确认与可用的只读 Redis 摘要共同核对；较新时间不能掩盖缺日。缓存缺失回 SQL，不为通过验收刷新证据。[交易日历](help:交易日历) 说明更新范围。
