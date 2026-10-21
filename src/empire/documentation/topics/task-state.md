<!-- topic:技术参考|任务状态字段 -->
<!-- summary:核对任务状态字段的正式字段、规则和维护边界。 -->
# 任务状态字段

## 调度与状态契约

[Redis collection-control](help:Redis%20collection-control) 是运行副本与嵌套字段字典，[MySQL app_setting](help:MySQL%20app_setting) 是持久计划配置。按任务结束后计算 next_due，同任务不重叠；Redis 丢失按已保存设置重建，不承诺恢复未归档断点。

## 完成边界

采集可继续下载，统一归档独立消费；只在整轮入队结束后等待本轮全部消息成功处理。运行记录与 [Redis archive-progress](help:Redis%20archive-progress) 不能用最高页冒充整轮完成。
