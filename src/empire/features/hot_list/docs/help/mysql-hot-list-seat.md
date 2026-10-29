<!-- topic:数据库参考|MySQL hot_list_seat -->
<!-- summary:通达信龙虎榜证券日期的类型化事实、关联约束与归档恢复边界，核心字段独立可查。 -->
<!-- group:MySQL -->
# MySQL hot_list_seat

## 用途与归属

数据集hot_list.tdx_unit，固定来源tdx，任务tdx-hot-list；features/hot_list的contract、dataset、query分别拥有契约、唯一事务写入和正式查询。日头、原因与席位按完整证券日关联，不保存成功响应原文。

## 结构与身份

| 字段 | SQL声明 | 含义 |
| --- | --- | --- |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一证券身份，来源请求使用六位代码；历史不随当前stock删除。 |
| `list_date` | `DATE NOT NULL` | 来源目录榜单日期，非公布时刻或统计起点。 |
| `seq` | `INT NOT NULL` | 完整证券日内规范排序序号；保留合法重复，不承诺跨修订稳定ID。 |
| `reason_code` | `VARCHAR(32) NOT NULL` | 来源T004原因码，不能作为证券日内唯一原因。 |
| `side` | `CHAR(1) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 来源T006买B/卖S方向。 |
| `seat_rank` | `INT NOT NULL` | 来源T007方向内排名；同名机构不同排名分别保存。 |
| `seat_name` | `VARCHAR(256) NOT NULL` | 来源T008席位名称，可能为当前营业部名称；不是唯一身份。 |
| `buy_amount` | `DECIMAL(28,8) NULL` | 来源T009买入金额万元，NULL未知、0为零。 |
| `sell_amount` | `DECIMAL(28,8) NULL` | 来源T010卖出金额万元，NULL未知、0为零。 |
| `net_amount` | `DECIMAL(28,8) NULL` | 来源je净额万元，允许负值，不以缺失方向倒推。 |
| `extension` | `JSON NOT NULL` | schema=1；bq1～bq4可空标签、yxyz/gsd未公开语义整数，白名单4KiB，不用于身份。 |

- `PRIMARY KEY (unified_code,list_date,seq)`：业务身份、范围查询或完整单元值域约束。
- `KEY ix_seat_name (seat_name,list_date,unified_code)`：业务身份、范围查询或完整单元值域约束。
- `CONSTRAINT ck_hot_seat_seq CHECK (seq >= 1 AND seq <= 10000)`：业务身份、范围查询或完整单元值域约束。
- `CONSTRAINT ck_hot_seat_rank CHECK (seat_rank >= 1 AND seat_rank <= 1000)`：业务身份、范围查询或完整单元值域约束。
- `CONSTRAINT ck_hot_seat_side CHECK (side IN ('B','S'))`：业务身份、范围查询或完整单元值域约束。
- `CONSTRAINT ck_hot_seat_positive CHECK ((buy_amount IS NULL OR buy_amount >= 0) AND (sell_amount IS NULL OR sell_amount >= 0))`：业务身份、范围查询或完整单元值域约束。

## 读写与关联

详情归档先核日头版本与内容摘要；相同或旧响应不读取子表，目录新建pending且两个明细计数为0时不读取空子表。已有正文变化仍读取完整旧记录比较，日头与子表继续同事务写入；正式查询及审计始终读取全部正文核对，不凭计数认定完整。


证券/榜单日期是共同关联，原因与席位序号保留当前完整单元的多重集合。日头及受影响子行同事务提交；重复内容零业务DML，可信摘要命中免SQL。列表按日期/代码稳定游标最多200行；详情最多1000原因/10000席位；审计20日期一批，范围最多2000日期。无到当前股票表的级联删除。

## 保留与恢复

目录退出保留历史；来源明确无席位保留状态及已有历史参考。普通立即补新增与待采；近7日每天、第8～90日7组轮转、90日外来源缺失30组轮转，强制初始化全历史重查。旧观测不覆盖当前版本；无来源版本，SQL观测上界限于最后内容变化，Redis摘要过期后不承诺其后的无变化核验上界。SQL提交后重放安全，归档成功即清队，失败留队；Redis丢失以SQL日头及重新目录恢复。

## 维护与相关说明

scripts/create_hot_list_schema.py显式新增三表；正常关闭程序，待归档为0，持实例及维护锁核对既有结构、数量和状态，不在启动执行DDL。人工改业务须先停止归档并失效相应摘要与证明；规范改变重建覆盖证据。

[通达信个股龙虎榜](help:通达信个股龙虎榜)
