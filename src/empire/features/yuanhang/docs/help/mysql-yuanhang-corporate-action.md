<!-- topic:数据库参考|MySQL yuanhang_corporate_action -->
<!-- summary:远航版原生历史结构化存储；来源固定ths_yuanhang。 -->
<!-- group:MySQL -->
# MySQL yuanhang_corporate_action

## 用途与归属

远航版PC原生协议的结构化事实或完整内容证明。日线归属ths-yuanhang-prices，权息与股本归属ths-yuanhang-financial；统一归档写入，历史查询读取。不是运行日志。

## 结构与身份

| 字段 | SQL声明 | 含义 |
| --- | --- | --- |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一证券键，六位代码加SH/SZ/BJ后缀；不随原生板块变化。 |
| `ex_date` | `DATE NOT NULL` | 除权除息生效日期，不是公告日期。 |
| `event_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范五个事件数值分量的SHA-256；与证券、日期共同定位一条完整事件。 |
| `bonus_ratio` | `DECIMAL(28,10) NOT NULL` | 每原股净送股或缩股比例，来源454减460；负值仅接受其他分量全0的纯缩股，须大于-1。 |
| `transfer_ratio` | `DECIMAL(28,10) NOT NULL` | 每原股转增比例，来源460。 |
| `rights_ratio` | `DECIMAL(28,10) NOT NULL` | 每原股配股比例，来源455。 |
| `rights_price` | `DECIMAL(28,10) NOT NULL` | 认购新增配股价格，元；有配股时须为正。 |
| `cash_per_share` | `DECIMAL(28,10) NOT NULL` | 每原股现金，元；沿来源口径。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (unified_code,ex_date,event_key)`
- `KEY idx_yuanhang_action_date (ex_date,unified_code)`
- `CONSTRAINT ck_yuanhang_action_values CHECK ((bonus_ratio >= 0 OR (bonus_ratio > -1 AND transfer_ratio = 0 AND rights_ratio = 0 AND rights_price = 0 AND cash_per_share = 0)) AND transfer_ratio >= 0 AND rights_ratio >= 0 AND rights_price >= 0 AND cash_per_share >= 0 AND (rights_ratio = 0 OR rights_price > 0))`

## 读写与关联

与其他远航表按unified_code和年度/生效日期关联；没有到当前股票表的删除级联。正式查询每页最多500条，年度单元最多366条；事件最多2000点，三种股本合计最多30000点，超限失败不截断。数值DECIMAL(28,10)，超出精度明确失败，不舍入。

## 保留与恢复

规范版本5保留同日不同事件，按日期和event_key规范排序及双键分页；内容修订改变事件身份，由完整响应替换该证券实际变化集合。纯缩股负值原样保存，同日多条事件不自动合并复权。须与规范5日线和联合金融证明重新核实。日线源质量异常单独标记，不更改事件分量来修正价格矛盾。

保留已归档历史，证券离开当前池不删除。完整单元修订只写实际变化，旧观察版本不覆盖更新确认。SQL事实、证明及该项目collection_state同事务。成功后公共归档器删除对应Redis消息，SQL失败保留重放。Redis丢失重新核实来源，不能承诺恢复未归档事实。

## 维护与相关说明

scripts/create_yuanhang_schema.py为显式新增入口；正常关闭程序、确认待归档为0后执行。维护前后核对已有业务及统一状态。应用启动只校验结构。直接维护SQL前须停止归档并失效对应可信摘要和覆盖证明。日常入口及数据语义见“远航版历史行情”。

原生空帧或严格校验的单点部分股本，须额外核实明确上市前状态；允许该形态407明确NULL但不填零，不完整响应不作为有效股本归档。上市前延期证券不向本表写入假空历史或零值；范围证据仅进入既有Redis断点与任务结果，每轮复查。原生已有历史与辅助上市状态矛盾时失败，已有事实保留。详见[远航版历史行情](help:远航版历史行情)。

## 与日线增量的关系

日线区间优化不改变本表粒度、字段、联合响应或唯一查询路径。权息与三口径股本仍按每日计划完整联合核验，同日同截止同股票池已完成时不重复请求；显式从头采集仍重核。不能以日线无变化推断金融事件无变化。共享摘要命名空间升级为ths_yuanhang_history_v2，旧摘要不再命中；首次回源只比较内容，不重复写相同业务。
