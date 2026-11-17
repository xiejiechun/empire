<!-- topic:数据库参考|MySQL graymarket_day -->
<!-- summary:东方财富完整交易日资金榜的结构化事实与集合证明，按交易日和证券查询，来源修订按统一事务归档。 -->
<!-- group:MySQL -->
# MySQL graymarket_day

## 用途与归属

固定来源eastmoney，数据集graymarket.eastmoney_day，项目eastmoney-graymarket。graymarket_day是实际日榜的总数和内容证明；graymarket_daily是一证券一交易日的原子事实。不是逐轮运行记录，不保存完整业务JSON。

## 结构与身份

| 字段 | SQL声明 | 含义 |
| --- | --- | --- |
| `trade_date` | `DATE NOT NULL` | 来源实际交易日；不使用休市日请求日期 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 按证券排序的全部规范事实SHA256 |
| `row_count` | `INT UNSIGNED NOT NULL` | 该日完整来源证券总数，1至10000 |
| `contract_version` | `INT UNSIGNED NOT NULL` | 规范字段和完整性契约版本 |

- `PRIMARY KEY (trade_date)`：业务身份、查询路径或数值边界约束。
- `CONSTRAINT ck_graymarket_count CHECK (row_count >= 1 AND row_count <= 10000)`：业务身份、查询路径或数值边界约束。

## 读写与关联

每日复盘整体行情以本表row_count与所选日实际成员数一致为完整日榜条件，缺头或不一致不计算资金和涨跌家数。不以当前股票目录数量替代榜内完整性，展示仍明确为资金榜样本。

资金流向同样在此完整性条件通过后才提供明盘、暗盘合计及当日个股净流入/流出前5榜；缺头或成员数量不一致时统计和榜单均为未知，不将部分成员当作完整榜。该读取沿用复盘同一只读快照，不新增写入或状态。行业自行汇总同样依赖完整资金日榜，另核验当前行业集合证明；不以部分日榜冒充板块总额，资金完整不代表每个当前行业的成员均有该日记录。当所有当前行业均无交集时板块方向榜为未知，完整个股日榜仍可正常查询。

graymarket.dataset为唯一业务写入路径，同日头、明细和collection_state同事务提交。无变化不执行业务DML，来源修订只改变化；较旧观测版本不覆盖。完整集合含来源市场值0中的北交所92代码族，证券身份按.BJ核验并参与摘要。日期主键支持当日集合，证券日期索引支持历史范围；query每页上限200，完整日审计最多10000行。

## 保留与恢复

已归档历史持续保留，Redis丢失按日期证明补缺。日期证明必须与明细键集合和内容一致，最大日期不代替连续覆盖。成功、相同或旧版无需写入均由统一归档器清队；失败保留。摘要使用日期身份和统一7天/10000键边界，盘中另有有界Redis快照，绝不进入本日终表；观察日15:30前的当日消息由数据集拒绝。

## 维护与相关说明

scripts/create_graymarket_schema.py是显式新增表入口；正常停机、持锁、队列归零并核对原业务。启动不建表，手工修改前停止归档并失效相应日期证明和摘要。

[东方财富明盘暗盘资金榜](help:东方财富明盘暗盘资金榜)
