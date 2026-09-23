# 新浪 A 股股票列表采集

首个真实来源插件为 `collector.sina_universe`，使用用户指定的 `Market_Center.getHQNodeData` 接口采集新浪 `hs_a` 当前股票集合，包含沪、深、北市场。

## 字段与统一代码

| 字段 | 含义 | 示例 |
| --- | --- | --- |
| code | 六位字符串代码，保留前导零 | 000001 |
| name | 股票名称，保留 ST 等名称标识 | 平安银行 |
| unified_code | 六位代码 + 点 + 市场 | 000001.SZ |
| market | SH 上海、SZ 深圳、BJ 北京 | SZ |
| source_symbol | 新浪来源代码 | sz000001 |

规范位于 `contracts/stocks.py`。市场按 `symbol` 的 sh/sz/bj 前缀识别，并验证后六位与 code 相同；未知前缀和冲突会停止该页入队，不静默过滤。

## 采集过程

1. 请求同站点 `Market_Center.getHQNodeStockCount?node=hs_a` 取得预期总数。
2. 新任务从第 1 页开始，每页默认 80 条，保持 `sort=symbol&asc=0&node=hs_a`。用户链接中的 page=3 仅是页面示例。
3. 按响应编码解析 JSON；已核验接口使用 GBK，以 GB18030 兼容处理中文。
4. 验证页内数量、身份唯一性、降序排序与跨页边界，发现明显分页漂移时停止。
5. 只将规范化身份字段和必要批次证据封装入 Redis，再原子推进游标。成功 HTTP 响应原文在解析结束后不持久保存。
6. 最后一页后验证下一页为空，并再次核对总数，然后入队完成证据。
7. 归档器每 60 秒检查，完整列表通过页连续性、数量与身份校验后，在一个 MySQL 事务中替换当前 `stock` 数据。提交后删除对应 Redis 消息。

请求总数、分页、重试和尾页校验都经过共享 `http.fetch`，与其他新浪插件共用 sina.com.cn 网站组。默认间隔 2 秒、并发 1 是项目初值，不是新浪官方限额。请求前检查容量，背压时保留数据和断点，不提前推进分页。

## 运行与续采

通过“采集管理 → 采集任务”执行、暂停、设置计划或从头重新采集。股票页只浏览当前业务结果。关闭桌面后，也可使用同一单实例保护和管理层：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m empire collect-stocks
.\.venv\Scripts\python.exe -X utf8 -m empire collect-stocks --fresh
```

禁用任务时命令行同样不能采集。正常暂停保留断点，恢复前启用并保存计划。完整性通过且 MySQL 发布成功后，采集记录才记为完成。

## 存储与错误

Redis 断点为 `<namespace>:checkpoint:sina-universe-v1`，保存批次、节点、页大小、预期总数、下一页、累计量、最后来源代码和阶段，无 TTL。开始、规范化分页及完成证据只在 Redis 业务队列中暂存，不另建 SQL 暂存表。

股票功能在 MySQL 仅保留当前 `stock` 表，主键为 `(source, unified_code)`；`generation` 标识当前发布批次。新列表不完整或数据库失败时不覆盖旧列表。显式重新开始后，已被游标证明替代的旧不完整暂存页可清除并记录原因；已完整有效、等待故障恢复的归档数据不能丢弃。

```sql
SELECT code, name, unified_code, market, source_symbol
FROM stock
WHERE source = 'sina' AND node = 'hs_a'
ORDER BY unified_code;
```

采集记录和归档记录分别保留每项目 100 条；错误保留每项目 300 条。HTTP 错误和业务解析错误的诊断样本只留 Redis，每条最多 64 KiB，带脱敏、原始长度、摘要及截断标记。重试成功不会删除先前错误；修复验证后才按选中 ID 清理。

这个集合来自新浪当前分页接口，不是交易所原子市场快照或历史任意时点股票池。首尾数量和排序校验只能发现明显漂移，不能据此宣称具备历史回测数据。

## 已有数据基准

2026-09-22 首次真实采集验证为 70 页、5,566 条；上海 2,319、深圳 2,902、北京 345。该数字是当次结果，后续数量由当前成功采集决定。存储简化时核验保留当前 5,566 条身份字段一致；具体 SQL 变更记录位于 `sql/changes`。
