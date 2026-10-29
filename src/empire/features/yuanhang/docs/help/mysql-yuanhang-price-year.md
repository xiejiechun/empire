<!-- topic:数据库参考|MySQL yuanhang_price_year -->
<!-- summary:远航版原生历史结构化存储；来源固定ths_yuanhang。 -->
<!-- group:MySQL -->
# MySQL yuanhang_price_year

## 用途与归属

远航版PC原生协议的结构化事实或完整内容证明。日线归属ths-yuanhang-prices，权息与股本归属ths-yuanhang-financial；统一归档写入，历史查询读取。不是运行日志。

## 结构与身份

| 字段 | SQL声明 | 含义 |
| --- | --- | --- |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一证券键，六位代码加SH/SZ/BJ后缀；不随原生板块变化。 |
| `quote_year` | `SMALLINT UNSIGNED NOT NULL` | 完整证券年度身份，1900至2100；源首条之前不建伪覆盖。 |
| `native_market` | `CHAR(4) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 实际请求板块USHA/USHT/USZA/USTM；不等于业务证券身份。 |
| `source_count` | `INT UNSIGNED NOT NULL` | 完整响应校验后独立交易日数；完整字段的精确重复行只计一次，同日冲突仍失败。 |
| `row_count` | `INT UNSIGNED NOT NULL` | 正式内容点数，须与键和正文摘要一同核对。 |
| `first_date` | `DATE NULL` | 单元中最早实际生效/交易日；合法空集合为NULL。 |
| `last_date` | `DATE NULL` | 单元中最晚实际生效/交易日；合法空集合为NULL。 |
| `key_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 按契约排序的完整业务键集合SHA256，不能仅用条数替代。 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 包含日期与规范十进制值、缺值的内容SHA256。 |
| `contract_version` | `SMALLINT UNSIGNED NOT NULL` | 消息与内容证明规范版本；规则改变须显式重建证明。 |
| `verified_through` | `DATE NOT NULL` | 该年最后内容变化时的来源核验截止日，已结束年最多为年末；无变化核验不刷新此列。 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 最后内容变化请求开始时刻，北京时间DATETIME(6)；重复确认顺序另由统一状态/可信摘要维护。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (unified_code,quote_year)`
- `CONSTRAINT ck_yuanhang_year_count CHECK (quote_year BETWEEN 1900 AND 2100 AND source_count = row_count AND row_count <= 366)`
- `CONSTRAINT ck_yuanhang_year_dates CHECK ((row_count = 0 AND first_date IS NULL AND last_date IS NULL) OR (row_count > 0 AND first_date IS NOT NULL AND last_date IS NOT NULL AND first_date <= last_date AND YEAR(first_date) = quote_year AND YEAR(last_date) = quote_year))`

## 读写与关联

与其他远航表按unified_code和年度/生效日期关联；没有到当前股票表的删除级联。正式查询每页最多500条，年度单元最多366条；事件最多2000点，三种股本合计最多30000点，超限失败不截断。数值DECIMAL(28,10)，超出精度明确失败，不舍入。

## 保留与恢复

当前规范版本5证明完整源日期集合和原值内容；仅完整日线字段表的相邻同日精确重复可合并，完整帧尺寸仍须通过，同日冲突、部分字段重复和日期倒序均失败。OHLC矛盾仍可完整归档并由查询标记；证明本身不担保每行适合回测。旧版本须完整重核，不能沿用为当前复权输入通过。

保留已归档历史，证券离开当前池不删除。完整单元修订只写实际变化，旧观察版本不覆盖更新确认。SQL事实、证明及该项目collection_state同事务。成功后公共归档器删除对应Redis消息，SQL失败保留重放。Redis丢失从SQL日期覆盖恢复，只补未确认范围；不能承诺恢复未归档事实。

## 维护与相关说明

scripts/create_yuanhang_schema.py为显式新增入口；正常关闭程序、确认待归档为0后执行。维护前后核对已有业务及统一状态。应用启动只校验结构。直接维护SQL前须停止归档并失效对应可信摘要和覆盖证明。日常入口及数据语义见“远航版历史行情”。

原生空帧或严格校验的单点部分股本，须额外核实明确上市前状态；允许该形态407明确NULL但不填零，不完整响应不作为有效股本归档。上市前延期证券不向本表写入假空历史或零值；范围证据仅进入既有Redis断点与任务结果，每轮复查。原生已有历史与辅助上市状态矛盾时失败，已有事实保留。详见[远航版历史行情](help:远航版历史行情)。

## 区间更新与版本

日线事实及年度主键不变。短区间只替换已验证日期，年度头按完整年现存正文重算，不删区间外历史。source_count为合并后完整年度独立交易日数。日期覆盖与各段观察版本保存在项目唯一collection_state的证券单元中；相邻同版本合并，至多366段/年、150年/证券，不保存行情正文。年度头的verified_through仍是最后业务内容变化时记录的连续核验上界，当前恢复覆盖须读取项目状态。旧状态通过scripts/migrate_yuanhang_ranges.py显式转换，事实与年度内容证明保持；应用启动不迁移。

迟到的不相交日期区间仍可补入，但不能降低年度证明的观察时间或覆盖较新原生市场。覆盖段决定各日期的写入权限，年度头不用于整年拒绝有效的局部补缺。
