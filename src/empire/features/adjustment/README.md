# 自算复权因子与行情业务包

本包独立拥有复权计算与页面，不归公司行动或开盘啦的私有实现目录。`bundle.py` 保留 `data.adjustment`、`ui.adjustment` 及原能力、两个计算准备声明，不新增采集任务、数据集或业务表。

| 修改内容 | 正式位置 |
| --- | --- |
| 价格/事件计算、错误与 ALGORITHM | `contract.py` |
| 输入证明、事件解码、停牌范围、收盘完整集合 | `inputs.py` |
| 同快照读取、计算、用途与新鲜度判定 | `query.py` |
| 页面交互与图表 | `ui.py`、`chart.py` |

`query.AdjustmentDataPlugin._history` 原 `REPEATABLE READ` 连接和 `conn.begin()` 贯穿证券身份、交易日历、价格、事件与证明读取。公司行动的 `contract` 和 `codec.decode` 是公开纯规则，不能自行建立数据库连接。跨业务价格API同样必须接收调用方现有conn，并保留按序验证、首个错误停止和有界读取；不能因为API拆分把一次计算拆成多个快照。

`inputs.close_prices` 已使用 E4 公开的 `iter_validated_days(conn, ...)` 与日期契约；迭代器沿用当前事务连接，按序校验，在首个错误停止。收盘时刻、缺日校验、暂停交易规则、缺事件退回原始K线、异常留空、税前每股单位及方案歧义规则保持。

使用与限制见 [复权说明](../../../../docs/adjustment-factors.md)。专项入口为 `tests/test_adjustment.py`、`tests/test_adjustment_query.py`、`tests/test_adjustment_chart.py`，正式输入链路见 `tests/integration/test_adjustment_pipeline.py`。开盘啦公共读取补丁的同conn/惰性/首错停止专项需同步运行；纯AST等价不能替代这些运行结果。

当前修订版输入不证明历史时点可知，当前成分不推导历史归属；价格不能用于成交和现金记账。目录迁移不新增数据库或修改用户保存的配置，计算仍按需运行。
