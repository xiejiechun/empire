# 东方财富股票回购

## 如何查看

在“采集管理 → 采集任务”搜索“股票回购（东方财富）”，执行采集；在“数据浏览”目录打开股票回购。支持按证券、初始方案公告日期和实施状态筛选，查看计划区间、累计实际回购及来源说明。配置保存于 MySQL，默认每天北京时间 18:00 核验，代理优先且允许回退；用户保存选择优先。网站组 eastmoney 的本机、代理出口及固定全站间隔均为 2000ms，初始程序声明及本机已保存策略一致，网站最多一个在途请求。

## 数据范围与更新

数据来自 RPTA_WEB_GETHGLIST_NEW，记录上市公司股票回购方案，**不是国债逆回购，也不是已完成注销事件库**。一个方案保存当前来源版本，历史方案保留；不保存每日累计快照、历次旧响应或行情字段。全市场范围按接口实际返回证券与股份类别保留，不按当前股票名单过滤。

### 生命周期与完整性设计

| 项目 | 正式契约 |
|---|---|
| 初始化 | 从来源首个方案编号开始，按 REPURCODE 字符串升序；首响应总数固定本轮范围，采完来源可见全量 |
| 完整单元 | 一页最多500方案，编号严格递增且跨页不得重复；后页始终请求 pageNumber=1，加 REPURCODE 大于上页末编号过滤，返回剩余总数须等于首总数减已入队数；实际页长等于 min(500,剩余数) |
| 完成 | 全部计划页校验并原子入队，最后记录完整集合摘要；整轮所有消息成功归档/确认且无残留才完成；条数不代替身份集合 |
| 集合证明归档 | 末批在既有fingerprint桶声明coverage元数据项，内容为contract/count/digest，版本为本批观测时刻；集合改变即回SQL更新原collection_state.coverage，避免末批方案全缓存命中漏更新。重复方案和相同集合证明均命中时免SQL；不增加表、消息路径或启动迁移 |
| 后续 | 每日全量回查，发现可见历史修订与补缺；不只查最大日期或仅新增编号；完整源集合变化时重新建立证明 |
| 中断 | 未入队数据从已有末编号重下载；一页按公共消息容量拆批，已入队子批不丢失；已入队页不等待归档便下载后页；尾页后仅重试归档确认，SQL提交后清队失败原消息重放 |
| Redis丢失 | SQL已归档历史保留，下一轮从首响应重新完整核验；不承诺Redis服务重启恢复待归档消息或内存断点 |
| 重新初始化 | 与普通全量核验相同；明确重新采集重置下载阶段；待确认轮次先确认归档，既有历史不删除；断点契约变化明确报错 |
| 修订 | UPD为来源日期版本，观测时刻只用于同日版本顺序；低UPD或同日更早观测响应不覆盖；内容及来源日期均相同零业务DML，不刷新观测时刻 |
| 限制 | 无来源快照令牌；新增/删除导致剩余统计变化即失败，不伪造完整。日期相同且数量相同的跨请求源端内容修订只能代表各页读取时的当前版本，不宣称同一秒快照；源端移除记录保留历史并使当前集合证明失配，需核实而不自动删除 |

## 字段与日期（存储设计卡，实施前提交）

一行代表 REPURCODE 指定的一份来源方案，固定来源 eastmoney，由数据集 repurchases.page 登记；主键 plan_id，证券统一 unified_code，无当前股票表外键。正式表 stock_repurchase_plan，无JSON业务列。


| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `plan_id` | `VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 来源REPURCODE方案编号，字符串排序。 |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 来源SECUCODE证券统一代码。 |
| `name` | `VARCHAR(100) NOT NULL` | 来源证券简称。 |
| `share_type` | `VARCHAR(80) NOT NULL` | 来源股份类别。 |
| `plan_date` | `DATE NOT NULL` | DIM_DATE初始方案公告自然日。 |
| `updated_date` | `DATE NOT NULL` | UPD来源更新日期，旧版本比较依据。 |
| `progress_code` | `VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 来源实施状态代码，未知代码保持原值。 |
| `plan_updated_date` | `DATE NULL` | UPDATEDATE方案更新自然日。 |
| `actual_through` | `DATE NULL` | DIM_DATE3累计实际统计截止自然日。 |
| `notice_date` | `DATE NULL` | NOTICEDATE累计回购公告日。 |
| `start_date` | `DATE NULL` | 回购开始日。 |
| `end_date` | `DATE NULL` | 回购结束日。 |
| `finish_date` | `DATE NULL` | 来源回购完成日，不是注销生效日。 |
| `shareholder_notice_date` | `DATE NULL` | 股东大会结果公告日。 |
| `advance_date` | `DATE NULL` | 来源进展公告日。 |
| `plan_price_upper` | `DECIMAL(28,8) NULL` | 计划回购价格上限，元/股，NULL未知。 |
| `plan_price_lower` | `DECIMAL(28,8) NULL` | 计划回购价格下限，元/股，NULL未知。 |
| `plan_quantity_upper` | `DECIMAL(28,8) NULL` | 计划回购数量上限，股，NULL未知。 |
| `plan_quantity_lower` | `DECIMAL(28,8) NULL` | 计划回购数量下限，股，NULL未知。 |
| `plan_amount_upper` | `DECIMAL(28,8) NULL` | 计划回购金额上限，元，NULL未知。 |
| `plan_amount_lower` | `DECIMAL(28,8) NULL` | 计划回购金额下限，元，NULL未知。 |
| `actual_price_upper` | `DECIMAL(28,8) NULL` | 累计实际回购价格上限，元/股，NULL未知。 |
| `actual_price_lower` | `DECIMAL(28,8) NULL` | 累计实际回购价格下限，元/股，NULL未知。 |
| `actual_quantity` | `DECIMAL(28,8) NULL` | 累计实际回购股数（股），NULL未知。 |
| `actual_amount` | `DECIMAL(28,8) NULL` | 累计实际回购金额（元），NULL未知。 |
| `objective` | `MEDIUMTEXT NULL` | 回购用途，最大64KiB UTF-8，不推断注销。 |
| `remark` | `MEDIUMTEXT NULL` | 方案说明，最大64KiB UTF-8。 |
| `progress_remark` | `MEDIUMTEXT NULL` | 累计进展说明，最大64KiB UTF-8。 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范业务内容SHA256，排除观测时刻。 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 当前存储版本观测时刻，北京时间；相同内容不刷新。 |

字段字典由 features/repurchases/contract.py 的 SOURCE_FIELDS 与 sql/schema.sql 同步：方案编号、证券、简称、股份类别、初始方案公告日 DIM_DATE、来源更新日 UPD、方案更新时间 UPDATEDATE、实际统计截止日 DIM_DATE3、实际公告日 NOTICEDATE、起止日、完成日、股东大会公告日、进展公告日；计划价格上下限(元/股)、数量上下限(股)、金额上下限(元)，累计实际价格上下限、股数、金额；实施代码、用途、方案说明、累计进展说明。日期为来源北京自然日，空值保持NULL，不用零代替。数量/金额/价格使用 DECIMAL(28,8)，精度增加或超界拒绝，数值以十进制字符串入消息。说明各限64KiB UTF-8，名称100字、股份类别80字；未知字段不入库，缺少声明字段失败。来源状态代码保留；006仅表示回购完成，不表示注销。

唯一内容位置为上述列；content_hash保存业务摘要，version_observed_at保存当前入库版本的北京时间观测时刻，仅有效内容或UPD改变才写。成功原始响应不落盘，错误按公共规则保留Redis有界脱敏样本。

## 查询、索引、容量与迁移

正式列表 SELECT 核心列 WHERE unified_code=:code AND plan_date BETWEEN :start AND :end ORDER BY plan_date DESC,plan_id DESC LIMIT 201；全市场同日期排序；可按 progress_code筛选。详情按plan_id点查返回完整说明。列表不投影TEXT；容量实验覆盖头查询只查plan_id、content_hash与日期；正式集合审计按200行游标读取全部规范列并核对content_hash。有界200行页，稳定日期/方案编号游标。

索引：(unified_code,plan_date,plan_id)、(plan_date,plan_id)、(progress_code,plan_date,plan_id)，加主键plan_id；不逐字段建索引。列表目标P95≤100ms、详情≤100ms；隔离容量实验50000行，表与索引≤256MiB，完整初始导入≤60秒，重复业务DML为0。2026-10-12首响应5537方案、500行ALL正文1177939字节；正式投影排除行情和重复展示字段，通用共享响应上限仍生效，不在插件扩大资源。预计每年新增2000方案、五年约15537行；按平均2KiB正文约32MiB，最大500行消息受统一消息容量校验。容量估算与隔离实测分别呈现；50000行实测159678464字节，导入34.36秒，分页不超过4.75ms，重复业务DML为0，见docs/evidence/repurchase-capacity-2026-10-12.json。

通过 scripts/create_repurchase_schema.py 独立维护新增表，应用启动不DDL。维护前正常关闭Empire、待归档Stream为0、取得现有维护锁，核对既有表数量、DDL与状态摘要；新增表后原有业务完全不变。无旧回购表/旧路径，无业务清理迁移；维护可重复核验现行结构，不丢弃数据。

## 限制与排错

用途中的“注销”“减少注册资本”只代表方案描述；本接口不提供可靠的已注销股数与注销生效日。计划区间与累计实际分别保留，实际数量可超过初始计划估算，不据此强制改写。金额元、数量股、价格元/股。公告自然日没有日内时刻；当前修订版本不能回填成当时已知信息，严格历史信号回放不适用。

分页总数变化、重复方案、字段或数值契约变化时保留断点并报错；不自动无限重读。网络异常沿用共享有界重试。数据页仅依赖MySQL；Redis可信摘要可辅助时效但不是浏览硬依赖。

## 相关说明

[采集管理](collection-management.md)、[数据库参考](database-reference.md)、[开发指南](collector-development-guide.md)。开发验证及实际已归档范围分别记录在交付证据，不把设计支持范围当作已经采完。

## 模块定位与隔离核验

回购正式路径集中于 `src/empire/features/repurchases/`，按契约、采集、归档、查询和页面定位；原任务、页面与保存设置保持。详见[包入口](../src/empire/features/repurchases/README.md)。旧 contracts/repurchases 及 plugins 下回购入口已退役，无兼容转发。

开发真实核验入口 `scripts/verify_repurchases.py` 只读正式连接定位与站点策略，在实际 UUID 不同的独立 MySQL、UUID 库及 Redis 前缀执行全市场方案游标全链路核对；不保存日常任务策略或写生产业务。显式提供 `--test-mysql-settings`、`--proxy-only` 与新的 build `--output`；中断资源仅凭 ownership 记录经 `--cleanup-only --run-state` 核实归属后清理。完整方案集合不是按证券请求的随机30股证明。

容量入口 `scripts/measure_repurchases.py --test-settings <独立配置> --source-proof <本轮通过来源报告> --output <新build报告>` 拒绝旧源码、失败或未清理来源证据，保持原50000行和预算；合成容量不代表生产完整覆盖。

2026-10-21本轮组织迁移的当前5万行真实隔离复测：原256MiB/60秒/列表与详情100ms/覆盖1000ms阈值保持。实际分配159678464字节、导入36.935秒、页4.229ms/证券2.092ms/状态4.704ms/详情1.000ms/覆盖745.896ms（原十次取最大值）；完整50000行集合内容一致、重复0业务DML、单修订1行、六项资源清理通过。[本轮容量报告](evidence/architecture-e6f-repurchase-capacity-2026-10-21.json)绑定本轮完整来源证明，旧2026-10-12报告保持历史。放大实验不是生产全市场覆盖或冷磁盘结论。
