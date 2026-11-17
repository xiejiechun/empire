<!-- topic:数据库参考|MySQL graymarket_daily -->
<!-- summary:东方财富完整交易日资金榜的结构化事实与集合证明，按交易日和证券查询，来源修订按统一事务归档。 -->
<!-- group:MySQL -->
# MySQL graymarket_daily

## 用途与归属

固定来源eastmoney，数据集graymarket.eastmoney_day，项目eastmoney-graymarket。graymarket_day是实际日榜的总数和内容证明；graymarket_daily是一证券一交易日的原子事实。不是逐轮运行记录，不保存完整业务JSON。

## 结构与身份

| 字段 | SQL声明 | 含义 |
| --- | --- | --- |
| `trade_date` | `DATE NOT NULL` | 来源实际交易日；不使用休市日请求日期 |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 证券身份，六位代码加.SH、.SZ或.BJ；市场值0中的92代码族属于北交所，不依赖当前股票目录过滤历史集合 |
| `name` | `VARCHAR(64) COLLATE utf8mb4_bin NOT NULL` | 来源证券名称，最长64字符 |
| `dark_flow` | `DECIMAL(24,0) NOT NULL` | 暗盘模型估算净资金，元，可负 |
| `visible_flow` | `DECIMAL(24,0) NOT NULL` | 明盘资金，元，可负 |
| `main_flow` | `DECIMAL(24,0) NOT NULL` | 含暗盘主力净流入，元，等于明盘加暗盘 |
| `dark_activity` | `DECIMAL(20,10) NOT NULL` | 暗盘活跃度小数，0.01表示1% |
| `price` | `DECIMAL(18,3) NOT NULL` | 来源价格千分原值换算为元 |
| `change_ratio` | `DECIMAL(20,10) NOT NULL` | 涨跌幅小数，可负 |
| `source_time` | `CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 来源行情HHMMSS，不冒充公布或采集时间 |
| `source_rank` | `INT UNSIGNED NOT NULL` | 来源序号允许跳号，不作为业务身份或连续性证明 |

- `PRIMARY KEY (trade_date, unified_code)`：业务身份、查询路径或数值边界约束。
- `KEY ix_graymarket_security_date (unified_code, trade_date)`：业务身份、查询路径或数值边界约束。
- `CONSTRAINT ck_graymarket_sum CHECK (dark_flow + visible_flow = main_flow)`：业务身份、查询路径或数值边界约束。
- `CONSTRAINT ck_graymarket_values CHECK (price >= 0 AND dark_activity >= 0 AND source_rank >= 1 AND source_rank <= 1000000)`：业务身份、查询路径或数值边界约束。

来源序号保留接口原值，不能当作暗盘资金排名；采集按已实测的固定来源顺序取得完整集合，查询按资金列另行排序。

## 读写与关联

每日复盘整体行情在完整日榜条件下聚合main_flow和change_ratio的正负零家数；资金标明“含暗盘模型测算”，家数只代表资金榜样本。真实0正常显示，缺头或集合不足时显示“缺少数据来源”；不回退盘中Redis或其他日期。

资金流向在同一完整日榜内聚合visible_flow、dark_flow，并按main_flow正值降序和负值升序各取前5只，同值按unified_code升序；返回当日name和change_ratio，涨跌幅小数乘100展示。按trade_date主键前缀限定单日最多10000行，每榜LIMIT 5、8秒SQL上限。完整榜内没有对应正/负值为已知空榜，缺完整日榜为未知。原始事实为个股模型资金，不包含来源板块榜或ETF净申赎。每日复盘另以当前industry_member按unified_code关联所选日main_flow自行汇总行业，标注“按当前成分股回看”，展示覆盖数量；缺失不按0、零覆盖不排名、部分覆盖明确提示；全部当前成员均无所选日资金时返回未知，不能冒充已知空榜。该结果不还原历史行业归属，不作为ETF净申赎。

graymarket.dataset为唯一业务写入路径，同日头、明细和collection_state同事务提交。无变化不执行业务DML，来源修订只改变化；较旧观测版本不覆盖。日期主键支持当日集合，证券日期索引支持历史范围；query每页上限200，完整日审计最多10000行。

观察日15:30前的当日消息拒绝进入本表，盘中快照仅保存于独立Redis键。

## 保留与恢复

已归档历史持续保留，Redis丢失按日期证明补缺。日期证明必须与明细键集合和内容一致，最大日期不代替连续覆盖。成功、相同或旧版无需写入均由统一归档器清队；失败保留。摘要使用日期身份和统一7天/10000键边界，无新增物理Redis键族。

## 维护与相关说明

scripts/create_graymarket_schema.py是显式新增表入口；正常停机、持锁、队列归零并核对原业务。启动不建表，手工修改前停止归档并失效相应日期证明和摘要。

[东方财富明盘暗盘资金榜](help:东方财富明盘暗盘资金榜)
