# 开盘啦字段字典与存储设计卡

2026-10-05 实施版本2。固定来源kaipanla；业务完整单位为一种数据的一个证券日。

## 精度与可逆规则

现存1016单元的数值最大12位整数、3位小数。DECIMAL(30,12)允许18位整数和12位小数，超界明确失败。float_mask保留来源int/float规范表达，present_mask区分盘口可选字段缺失；不将未知量单位转换为股/手。全部普通数值参与业务摘要，来源metadata时间除外。

## 序列字段映射

### trend

来源数组位置0为时间，位置1起依次对应：price, average_price, source_volume, source_flag。

seq保存来源顺序，分钟主键按source_time；竞价按seq，同分钟所有点保留。
### auction

来源数组位置0为时间，位置1起依次对应：price, source_flag, source_volume。

seq保存来源顺序，分钟主键按source_time；竞价按seq，同分钟所有点保留。
### volume

来源数组位置0为时间，位置1起依次对应：source_volume, source_turnover, source_flag。

seq保存来源顺序，分钟主键按source_time；竞价按seq，同分钟所有点保留。
### trades

来源数组位置0为时间，位置1起依次对应：price, source_flag, source_volume, source_field_4, source_field_5, source_field_6, source_field_7。

主键/分页/时间索引见DDL。分笔采用200点类型化二进制块：uint32来源秒数、uint16浮点/负零类型位图、7个int64/IEEE754 binary64类型联合数值，zlib6压缩；单块原文最多12400字节，block_hash校验压缩内容摘要，安全解码校验结尾和边界。未知字段4～7保留位置语义，不猜测方向。
### entrust

来源数组位置0为时间，位置1起依次对应：buy_volume, sell_volume, buy_turnover, sell_turnover。

seq保存来源顺序，分钟主键按source_time；竞价按seq，同分钟所有点保留。
### large_order

来源数组位置0为时间，位置1起依次对应：net_amount。

seq保存来源顺序，分钟主键按source_time；竞价按seq，同分钟所有点保留。

## 日摘要字段

real中的以下字段分别存入同名DECIMAL列；time为来源数值，不转为时间戳。缺失可选字段在SQL为NULL、present_mask未置位；显式可选NULL仍保存SQL NULL且存在位置位，反向返回None；原值为零则保存非NULL的零。必需字段为空仍由来源校验拒绝。必需行情继续由来源校验器约束。

time, up_px, avg_px, low_px, down_px, high_px, last_px, open_px, pe_rate, jtPeRate, TTMPeRate, amount_in, amplitude, px_change, vol_ratio, amount_out, dyn_pb_rate, phcj_volume, entrust_rate, market_value, total_amount, total_shares, phcj_turnover, px_change_rate, total_turnover, turnover_ratio, circulation_value, circulation_amount, actualcirculation_value

20档b1～b10/s1～s10映射side/level/price/source_volume；零档位保存。weituo的totalb/totals/avg_askpx/avg_bidpx保留在product_extra.book。name/status/sourcetype/preclose_px在product_extra.fields保存。其他未登记字段明确拒绝，不能无上限兜底。

## 父头与扩展

kind/证券/日期、source_code、上市日/上市来源/市场起点、content_hash、version_observed_at、contract_version=2、point_count、key_set_hash为普通列。identity_extra只保留官方别名证明；product_extra仅允许来源日级统计白名单；source_metadata只允许time/time2/ts，三个扩展各16KiB上限。

## 全部SQL字段与约束

### stock_market_day

| 字段 | SQL类型 | NULL |
| --- | --- | --- |
| kind | varchar(16) collate "ascii_bin" | False |
| unified_code | varchar(9) collate "ascii_bin" | False |
| trade_date | date | False |
| source_code | varchar(6) collate "ascii_bin" | True |
| listing_date | date | False |
| listing_source | varchar(16) collate "utf8mb4_bin" | False |
| market_start | date | False |
| identity_extra | json | False |
| product_extra | json | False |
| source_metadata | json | False |
| content_hash | char(64) collate "ascii_bin" | False |
| version_observed_at | datetime | False |
| contract_version | smallint | False |
| point_count | integer | False |
| key_set_hash | char(64) collate "ascii_bin" | False |

主键：kind, unified_code, trade_date

### stock_intraday_trend

| 字段 | SQL类型 | NULL |
| --- | --- | --- |
| unified_code | varchar(9) collate "ascii_bin" | False |
| trade_date | date | False |
| seq | integer | False |
| source_time | time | False |
| float_mask | smallint | False |
| price | decimal(30, 12) | False |
| average_price | decimal(30, 12) | False |
| source_volume | decimal(30, 12) | False |
| source_flag | decimal(30, 12) | False |

主键：unified_code, trade_date, source_time

### stock_opening_auction

| 字段 | SQL类型 | NULL |
| --- | --- | --- |
| unified_code | varchar(9) collate "ascii_bin" | False |
| trade_date | date | False |
| seq | integer | False |
| source_time | time | False |
| float_mask | smallint | False |
| price | decimal(30, 12) | False |
| source_flag | decimal(30, 12) | False |
| source_volume | decimal(30, 12) | False |

主键：unified_code, trade_date, seq

### stock_minute_volume

| 字段 | SQL类型 | NULL |
| --- | --- | --- |
| unified_code | varchar(9) collate "ascii_bin" | False |
| trade_date | date | False |
| seq | integer | False |
| source_time | time | False |
| float_mask | smallint | False |
| source_volume | decimal(30, 12) | False |
| source_turnover | decimal(30, 12) | False |
| source_flag | decimal(30, 12) | False |

主键：unified_code, trade_date, source_time

### stock_intraday_trade_block

| 字段 | SQL类型 | NULL |
| --- | --- | --- |
| unified_code | varchar(9) collate "ascii_bin" | False |
| trade_date | date | False |
| block_seq | integer | False |
| first_seq | integer | False |
| last_seq | integer | False |
| first_time | time | False |
| last_time | time | False |
| point_count | smallint | False |
| format_version | smallint | False |
| body | blob | False |
| block_hash | char(64) | False |

主键：unified_code, trade_date, block_seq

### stock_minute_entrust

| 字段 | SQL类型 | NULL |
| --- | --- | --- |
| unified_code | varchar(9) collate "ascii_bin" | False |
| trade_date | date | False |
| seq | integer | False |
| source_time | time | False |
| float_mask | smallint | False |
| buy_volume | decimal(30, 12) | False |
| sell_volume | decimal(30, 12) | False |
| buy_turnover | decimal(30, 12) | False |
| sell_turnover | decimal(30, 12) | False |

主键：unified_code, trade_date, source_time

### stock_large_order_trend

| 字段 | SQL类型 | NULL |
| --- | --- | --- |
| unified_code | varchar(9) collate "ascii_bin" | False |
| trade_date | date | False |
| seq | integer | False |
| source_time | time | False |
| float_mask | smallint | False |
| net_amount | decimal(30, 12) | False |

主键：unified_code, trade_date, source_time

### stock_daily_quote

| 字段 | SQL类型 | NULL |
| --- | --- | --- |
| unified_code | varchar(9) collate "ascii_bin" | False |
| trade_date | date | False |
| float_mask | bigint | False |
| present_mask | bigint | False |
| time | decimal(30, 12) | True |
| up_px | decimal(30, 12) | True |
| avg_px | decimal(30, 12) | True |
| low_px | decimal(30, 12) | True |
| down_px | decimal(30, 12) | True |
| high_px | decimal(30, 12) | True |
| last_px | decimal(30, 12) | True |
| open_px | decimal(30, 12) | True |
| pe_rate | decimal(30, 12) | True |
| jtPeRate | decimal(30, 12) | True |
| TTMPeRate | decimal(30, 12) | True |
| amount_in | decimal(30, 12) | True |
| amplitude | decimal(30, 12) | True |
| px_change | decimal(30, 12) | True |
| vol_ratio | decimal(30, 12) | True |
| amount_out | decimal(30, 12) | True |
| dyn_pb_rate | decimal(30, 12) | True |
| phcj_volume | decimal(30, 12) | True |
| entrust_rate | decimal(30, 12) | True |
| market_value | decimal(30, 12) | True |
| total_amount | decimal(30, 12) | True |
| total_shares | decimal(30, 12) | True |
| phcj_turnover | decimal(30, 12) | True |
| px_change_rate | decimal(30, 12) | True |
| total_turnover | decimal(30, 12) | True |
| turnover_ratio | decimal(30, 12) | True |
| circulation_value | decimal(30, 12) | True |
| circulation_amount | decimal(30, 12) | True |
| actualcirculation_value | decimal(30, 12) | True |

主键：unified_code, trade_date

### stock_daily_quote_level

| 字段 | SQL类型 | NULL |
| --- | --- | --- |
| unified_code | varchar(9) collate "ascii_bin" | False |
| trade_date | date | False |
| side | char(1) collate "ascii_bin" | False |
| level | tinyint | False |
| price | decimal(30, 12) | False |
| source_volume | decimal(30, 12) | False |
| float_mask | tinyint | False |

主键：unified_code, trade_date, side, level

