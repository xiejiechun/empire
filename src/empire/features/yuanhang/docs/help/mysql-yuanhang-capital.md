<!-- topic:数据库参考|MySQL yuanhang_capital -->
<!-- summary:远航版原生历史结构化存储；来源固定ths_yuanhang。 -->
<!-- group:MySQL -->
# MySQL yuanhang_capital

## 用途与归属

远航版PC原生协议的结构化事实或完整内容证明。日线归属ths-yuanhang-prices，权息与股本归属ths-yuanhang-financial；统一归档写入，历史查询读取。不是运行日志。

## 结构与身份

| 字段 | SQL声明 | 含义 |
| --- | --- | --- |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一证券键，六位代码加SH/SZ/BJ后缀；不随原生板块变化。 |
| `capital_kind` | `VARCHAR(11) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | total总股本、circulating普通流通股、free_float自由流通股。 |
| `effective_date` | `DATE NOT NULL` | 该口径独立的来源生效日期，不按其他口径行号关联。 |
| `shares` | `DECIMAL(28,10) NULL` | 该生效日股本余额，股；可用数值须正数，只有circulating明确源缺值可为NULL。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (unified_code,capital_kind,effective_date)`
- `CONSTRAINT ck_yuanhang_capital_kind CHECK (capital_kind IN ('total','circulating','free_float'))`
- `CONSTRAINT ck_yuanhang_capital_shares CHECK ((shares IS NOT NULL AND shares > 0) OR (shares IS NULL AND capital_kind = 'circulating'))`

## 读写与关联

与其他远航表按unified_code和年度/生效日期关联；没有到当前股票表的删除级联。正式查询每页最多500条，年度单元最多366条；事件最多2000点，三种股本合计最多30000点，超限失败不截断。数值DECIMAL(28,10)，超出精度明确失败，不舍入。

## 保留与恢复

必需金融数值明确NULL时先按任务共用预算切换健康身份节点并重取完整联合响应；持续缺值不向本表发布事实或完整证明，旧内容及断点保留。不拼接部分响应，字段、业务键与规范版本不变。重试及诊断见[远航版历史行情](help:远航版历史行情)。

规范版本5保留三种股本口径、生效日期和明确NULL流通股点。命中NULL点的截至日余额仍未知，不使用更早非空值填充；另外两口径、缺字段、零或负数仍失败。联合证明须重新核实，不用股本变动解释或改写日线源OHLC矛盾，也不将旧证明冒充新版本通过。

保留已归档历史，证券离开当前池不删除。完整单元修订只写实际变化，旧观察版本不覆盖更新确认。SQL事实、证明及该项目collection_state同事务。成功后公共归档器删除对应Redis消息，SQL失败保留重放。Redis丢失重新核实来源，不能承诺恢复未归档事实。

## 维护与相关说明

scripts/create_yuanhang_schema.py为显式新增入口；正常关闭程序、确认待归档为0后执行。维护前后核对已有业务及统一状态。应用启动只校验结构。直接维护SQL前须停止归档并失效对应可信摘要和覆盖证明。日常入口及数据语义见“远航版历史行情”。

原生空帧或严格校验的单点部分股本，须额外核实明确上市前状态；允许该形态407明确NULL但不填零，不完整响应不作为有效股本归档。上市前延期证券不向本表写入假空历史或零值；范围证据仅进入既有Redis断点与任务结果，每轮复查。原生已有历史与辅助上市状态矛盾时失败，已有事实保留。详见[远航版历史行情](help:远航版历史行情)。

## 与日线增量的关系

日线区间优化不改变本表粒度、字段、联合响应或唯一查询路径。权息与三口径股本仍按每日计划完整联合核验，同日同截止同股票池已完成时不重复请求；显式从头采集仍重核。不能以日线无变化推断金融事件无变化。共享摘要命名空间升级为ths_yuanhang_history_v2，旧摘要不再命中；首次回源只比较内容，不重复写相同业务。

## 采集百分比

本轮证券范围；已采集或可信覆盖跳过的证券数。使用本轮实际计划和已成功处理数量计算；准备范围期间不猜总量，空计划表示无需处理。百分比达到100%不替代完整集合校验或本轮归档确认；失败仍按实际结果显示。
