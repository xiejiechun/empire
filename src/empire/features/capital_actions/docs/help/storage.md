<!-- topic:技术参考|增发送配存储与断点 -->
<!-- summary:核对增发送配存储与断点的正式字段、规则和维护边界。 -->
# 增发送配存储与断点

## 字段与规则

分红送转、增发和配股各自独立任务与查询页面，入口在数据浏览目录的“增发送配”。分红以当前股票目录为池，按报告期一次取最多10000条并组装完整历史，未证实历史的证券先发现日期，增发、配股核验全部来源集合。普通采集续跑未完成断点，完成后下一轮重查全部可得历史；重新初始化重建范围，不删除历史。Redis 丢失后从完整范围重查。

字段、身份与索引分别见 [MySQL dividend_plan](help:MySQL%20dividend_plan)、[MySQL additional_issue](help:MySQL%20additional_issue)、[MySQL rights_issue](help:MySQL%20rights_issue)。规范单位和来源限制见各业务数据手册。

增发的来源 rec_id 可同时关联新旧代码，分别保留；配股同登记日的不同认购代码或缴款起日分别保留。缺少的旧发行日、缴款结束日、上市日不编造。增发/配股不包含来源未提供的公告时间、预案取消历史，不能用于公告前选股。

统一摘要命名空间为 `dividends`、`additional_issues`、`rights_issues`，每证券完整单元及最终范围证明各一项。collection_state 保存各单元的最近 SQL 确认版本和最终范围摘要；数据准备将正式 SQL 业务集合与证明比较，缺失/异常仍失败。源端移除的历史业务仍保留，不能自动删库来凑总数。

分红契约 dividends.unit@3 的业务键包含市场、代码、报告期、公告日及每股派息/送股/转增，保留同日期不同金额的并列来源方案，不自动求和。金额身份将NULL/零视为同一键分量，业务值仍保留未知与实际零值的差异。每证券历史发现标记保存在collection_state.units.history_discovered_at，归档时间是证明上界；完整集合指纹仍只比较业务内容。旧键通过 scripts/migrate_dividend_identity.py 显式无损重算并失效旧覆盖、缓存及断点，从头重查；金额身份变化无法据此裁定同一方案修订。

现行增发 additional_issues.unit@3 在原 additional_issue.payload.detail 保存规范明细或明确暂无状态：availability=unavailable、source_error_code=0/-1005，可选last_available保留上次有效明细。未采字段不直接转暂无；有效明细仍为原17项字段，数据身份不变。暂无参与摘要与旧版防覆盖，相同内容无业务DML，成功仍统一清队。升级只在程序关闭、队列为空时显式执行 scripts/migrate_issue_availability.py；保留业务行和观察水位，重建受影响完成证明/断点，保留规范内容不变且可验证的证券摘要。启动不自动迁移。历史未知记录仅在当前完整集合摘要精确匹配后标为当前来源范围之外，不伪造暂无。

范围准备复用collection_state现行单元count/digest/observed_at与完整SQL行核对。未增加成员清单、业务表、状态字段或迁移；只有整个证券单元匹配才能投影日期。无匹配证明的保留历史与未知缺口仍阻断，不能从聚合摘要猜测子集。
