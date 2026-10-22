<!-- topic:数据库参考|MySQL hot_list_day -->
<!-- summary:通达信龙虎榜证券日期的类型化事实、关联约束与归档恢复边界，核心字段独立可查。 -->
<!-- group:MySQL -->
# MySQL hot_list_day

## 用途与归属

数据集hot_list.tdx_unit，固定来源tdx，任务tdx-hot-list；features/hot_list的contract、dataset、query分别拥有契约、唯一事务写入和正式查询。日头、原因与席位按完整证券日关联，不保存成功响应原文。

## 结构与身份

| 字段 | SQL声明 | 含义 |
| --- | --- | --- |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一证券身份，来源请求使用六位代码；历史不随当前stock删除。 |
| `list_date` | `DATE NOT NULL` | 来源目录榜单日期，非公布时刻或统计起点。 |
| `directory_listed` | `BOOLEAN NOT NULL` | 是否仍在本轮完整来源日期目录；退出目录的历史保留。 |
| `detail_status` | `VARCHAR(20) NOT NULL` | pending待采、present完整席位、partial原因关联部分缺失、source_empty明确无席位。 |
| `reason_count` | `INT NOT NULL` | 当前保留原因行数，上限1000，来源并列行不合并。 |
| `seat_count` | `INT NOT NULL` | 当前保留席位行数，上限10000。 |
| `auxiliary` | `JSON NOT NULL` | schema=1；counts、institution_count、related白名单；64KiB，两个数组各最多500，查询时刻辅助信息。 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 当前响应规范内容SHA256；source_empty保留旧参考时不代表旧子表摘要。 |
| `version_observed_at` | `DATETIME(6) NULL` | 当前存储内容版本观测，北京时间；pending为NULL，相同内容不更新时间。 |

- `PRIMARY KEY (unified_code,list_date)`：业务身份、范围查询或完整单元值域约束。
- `KEY ix_date (list_date,unified_code)`：业务身份、范围查询或完整单元值域约束。
- `CONSTRAINT ck_hot_list_listed CHECK (directory_listed IN (0,1))`：业务身份、范围查询或完整单元值域约束。
- `CONSTRAINT ck_hot_list_status CHECK (detail_status IN ('pending','present','partial','source_empty'))`：业务身份、范围查询或完整单元值域约束。
- `CONSTRAINT ck_hot_list_counts CHECK (reason_count >= 0 AND reason_count <= 1000 AND seat_count >= 0 AND seat_count <= 10000)`：业务身份、范围查询或完整单元值域约束。

## 读写与关联

证券/榜单日期是共同关联，原因与席位序号保留当前完整单元的多重集合。日头及受影响子行同事务提交；重复内容零业务DML，可信摘要命中免SQL。列表按日期/代码稳定游标最多200行；详情最多1000原因/10000席位；审计20日期一批，范围最多2000日期。无到当前股票表的级联删除。

## 保留与恢复

目录退出保留历史；来源明确无席位保留状态及已有历史参考。普通补缺及90日回查，强制初始化全历史重查。旧观测不覆盖当前版本；无来源版本，SQL观测上界限于最后内容变化，Redis摘要过期后不承诺其后的无变化核验上界。SQL提交后重放安全，归档成功即清队，失败留队；Redis丢失以SQL日头及重新目录恢复。

## 维护与相关说明

scripts/create_hot_list_schema.py显式新增三表；正常关闭程序，待归档为0，持实例及维护锁核对既有结构、数量和状态，不在启动执行DDL。人工改业务须先停止归档并失效相应摘要与证明；规范改变重建覆盖证据。

[通达信个股龙虎榜](help:通达信个股龙虎榜)
