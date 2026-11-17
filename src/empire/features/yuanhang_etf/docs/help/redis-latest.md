<!-- topic:数据库参考|Redis yuanhang-etf-latest -->
<!-- summary:ETF单份易失最新值的字段、期限、清理与恢复。 -->
<!-- group:Redis -->
# Redis yuanhang-etf-latest

## 用途与归属

归ths-yuanhang-etf-latest项目，正式查询由yuanhang.etf.latest.query提供。只经公共publish_volatile准入，全部等待结束后复核隔离；不入归档Stream，不写SQL业务或collection_state。

## 结构与身份

`<namespace>:yuanhang:etf:latest`，Hash，固定两个字段：version为UTC微秒整数版本，body为z1:前缀的Base64封装zlib正文，编码与解压JSON各最多24MiB；只保留这一份正文。Lua原子拒绝不更新的旧版本、HSET两个字段并EXPIRE604800秒。读取用Lua先检查HSTRLEN再HMGET，防止损坏正文无界读取。解压严格限制24MiB、完整结束及无多余尾部，不接收旧JSON格式。

解压正文白名单schema=1、catalog_hash、observed_at、rows。catalog_hash绑定按代码排序的code/name/native_market目录。observed_at为带时区的本轮起始采样时间；rows最多5000，每只最多4KiB，严格无重复、排序及全目标集合。

| rows字段 | 类型/单位 | 含义与空值 |
| --- | --- | --- |
| code/name/native_market | 字符串 | 六位代码加后缀、来源名称、USHJ/USZJ，必须与冻结目录一致 |
| previous_close/open/high/low/latest | 十进制字符串或NULL，元 | 来源6/7/8/9/10，不改精度，不以0代NULL |
| volume/amount | 十进制字符串或NULL，份/元 | 来源13/19，不乘100 |
| net_value | 十进制字符串或NULL，元 | 来源3397净值，日期未知；不是实时估值 |
| quote_at/net_value_date | NULL | 当前协议未证明报价时刻与净值日期，不能用采样时间填充 |

## 读写与关联

查询派生unified_code、change/change_percent/amplitude（计算）、observed_at、source_time_unknown、sampling_stale（超过180秒）和availability；不重复持久保存派生值。数值排序使用Decimal，缺值置后，同值按代码；分页绑定version和查询签名，版本变化明确要求刷新。每页最多500，不建立历史快照键。

## 保留与恢复

成功整份替换后7天TTL。失败保留旧完整值和原采样时间；退出证券随下一份完整目录被替换。只保留最新，没有分钟历史，7天不是新鲜承诺；Redis重启丢失后重新采样，不从SQL恢复盘中报价。错误样本及运行记录使用公共每项目限额，业务数据不套错误上限丢弃。

## 维护与相关说明

[同花顺远航版ETF最新行情](help:同花顺远航版ETF最新行情)
