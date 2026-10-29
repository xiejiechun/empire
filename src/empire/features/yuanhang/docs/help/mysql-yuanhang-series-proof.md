<!-- topic:数据库参考|MySQL yuanhang_series_proof -->
<!-- summary:远航版原生历史结构化存储；来源固定ths_yuanhang。 -->
<!-- group:MySQL -->
# MySQL yuanhang_series_proof

## 用途与归属

远航版PC原生协议的结构化事实或完整内容证明。日线归属ths-yuanhang-prices，权息与股本归属ths-yuanhang-financial；统一归档写入，历史查询读取。不是运行日志。

## 结构与身份

| 字段 | SQL声明 | 含义 |
| --- | --- | --- |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一证券键，六位代码加SH/SZ/BJ后缀；不随原生板块变化。 |
| `series_kind` | `VARCHAR(7) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | actions权息或capital股本；两个头与事实在同事务更新。 |
| `native_market` | `CHAR(4) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 实际请求板块USHA/USHT/USZA/USTM；不等于业务证券身份。 |
| `source_count` | `INT UNSIGNED NOT NULL` | 验证后完整单元中的来源点数。 |
| `row_count` | `INT UNSIGNED NOT NULL` | 正式内容点数，须与键和正文摘要一同核对。 |
| `first_date` | `DATE NULL` | 单元中最早实际生效/交易日；合法空集合为NULL。 |
| `last_date` | `DATE NULL` | 单元中最晚实际生效/交易日；合法空集合为NULL。 |
| `key_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 按契约排序的完整业务键集合SHA256，不能仅用条数替代。 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 包含日期与规范十进制值、缺值的内容SHA256。 |
| `contract_version` | `SMALLINT UNSIGNED NOT NULL` | 消息与内容证明规范版本；规则改变须显式重建证明。 |
| `response_group` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 同一完整211规范响应的内容摘要，绑定权息和股本，不含账号或会话。 |
| `total_count` | `INT UNSIGNED NOT NULL` | 总股本点数；权息证明固定为0。 |
| `circulating_count` | `INT UNSIGNED NOT NULL` | 普通流通股点数；权息证明固定为0。 |
| `free_float_count` | `INT UNSIGNED NOT NULL` | 自由流通股点数；权息证明固定为0。 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 最后内容变化请求开始时刻，北京时间DATETIME(6)；重复确认顺序另由统一状态/可信摘要维护。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (unified_code,series_kind)`
- `CONSTRAINT ck_yuanhang_series_kind CHECK (series_kind IN ('actions','capital'))`
- `CONSTRAINT ck_yuanhang_series_count CHECK (source_count = row_count AND ((series_kind = 'actions' AND row_count <= 2000 AND total_count = 0 AND circulating_count = 0 AND free_float_count = 0) OR (series_kind = 'capital' AND row_count <= 30000 AND total_count > 0 AND circulating_count > 0 AND free_float_count > 0 AND total_count + circulating_count + free_float_count = row_count)))`
- `CONSTRAINT ck_yuanhang_series_dates CHECK ((row_count = 0 AND first_date IS NULL AND last_date IS NULL) OR (row_count > 0 AND first_date IS NOT NULL AND last_date IS NOT NULL AND first_date <= last_date))`

## 读写与关联

与其他远航表按unified_code和年度/生效日期关联；没有到当前股票表的删除级联。正式查询每页最多500条，年度单元最多366条；事件最多2000点，三种股本合计最多30000点，超限失败不截断。数值DECIMAL(28,10)，超出精度明确失败，不舍入。

## 保留与恢复

当前金融联合证明使用规范版本5，事件键摘要包括除权日和event_key，股本内容摘要包括明确NULL流通股点；重核后才可用于计算。来源日线质量与同日事件歧义独立判断，金融证明齐全不能掩盖这些用途限制。

保留已归档历史，证券离开当前池不删除。完整单元修订只写实际变化，旧观察版本不覆盖更新确认。SQL事实、证明及该项目collection_state同事务。成功后公共归档器删除对应Redis消息，SQL失败保留重放。Redis丢失重新核实来源，不能承诺恢复未归档事实。

## 维护与相关说明

scripts/create_yuanhang_schema.py为显式新增入口；正常关闭程序、确认待归档为0后执行。维护前后核对已有业务及统一状态。应用启动只校验结构。直接维护SQL前须停止归档并失效对应可信摘要和覆盖证明。日常入口及数据语义见“远航版历史行情”。

原生空帧或严格校验的单点部分股本，须额外核实明确上市前状态；允许该形态407明确NULL但不填零，不完整响应不作为有效股本归档。上市前延期证券不向本表写入假空历史或零值；范围证据仅进入既有Redis断点与任务结果，每轮复查。原生已有历史与辅助上市状态矛盾时失败，已有事实保留。详见[远航版历史行情](help:远航版历史行情)。

## 与日线增量的关系

日线区间优化不改变本表粒度、字段、联合响应或唯一查询路径。权息与三口径股本仍按每日计划完整联合核验，同日同截止同股票池已完成时不重复请求；显式从头采集仍重核。不能以日线无变化推断金融事件无变化。共享摘要命名空间升级为ths_yuanhang_history_v2，旧摘要不再命中；首次回源只比较内容，不重复写相同业务。
