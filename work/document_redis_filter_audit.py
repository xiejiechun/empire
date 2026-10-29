import inspect,json,hashlib
from datetime import datetime,UTC
from pathlib import Path
from empire.bootstrap import build_manager
from empire.core.config import load_config
live=json.loads(Path('docs/evidence/redis-filter-live-2026-10-29.json').read_text(encoding='utf-8'))
m=build_manager(load_config());cat=m.entries['dataset.astock'].plugin
keys={
'calendar':'月份完整日历', 'capital_actions':'证券完整单元＋整轮范围证明', 'financial_statements':'证券完整报表＋整轮范围证明',
'holders':'证券完整股东报告、来源缺口＋范围证明', 'index_prices':'指数年份或覆盖单元', 'indices':'指数目录及单指数成员',
'industries':'完整当前行业目录', 'kaipanla':'证券＋交易日（独立产品）', 'listings':'单证券上市资料＋范围证明',
'listing_status':'月份＋来源日期覆盖', 'name_changes':'市场完整更名集合', 'news':'来源新闻ID，包含来源修订版本',
'performance':'证券/报告期/日期×市场完整单元＋范围证明', 'repurchases':'方案ID＋最终覆盖证明',
'stocks':'统一当前股票完整列表（两来源共享current）', 'st_events':'市场完整ST事件集合',
'suspensions':'完整来源记录身份＋日期覆盖证明', 'themes':'日期题材列表 / 单题材详情与来源版本',
'ths_capital':'单证券资本运作完整内容、可用性＋范围证明', 'trading_rules':'单组官方规则与引用',
'unlocks':'月份市场父子业务集合＋范围证明', 'unlock_industries':'月份、基准日期＋范围证明',
'yuanhang':'日线按证券×覆盖日期；权息股本按证券完整响应（共用摘要命名空间）',
'yuanhang_limits':'完整日期池 / 日期＋证券原因；盘中快照另走Redis-only路径',
}
rows=[]
for ident,spec in m.entries['collection.control'].plugin.definitions.items():
 collector=m.entries[m.providers[spec.capability]].plugin
 family=type(collector).__module__.split('.')[2]
 contrib=[c for c in cat.contributions if ident in c.projects.values()]
 assert contrib,ident
 assert all(callable(getattr(c.mapping,'fingerprint_plan',None)) and callable(getattr(c.mapping,'fingerprint_subset',None)) for c in contrib),ident
 namespaces=sorted({c.namespace for c in contrib})
 buckets=[b for b in live['buckets'] if b['namespace'] in namespaces]
 samples=sum(b['sample_size'] for b in buckets);valid=sum(b['valid_sample'] for b in buckets)
 count=sum(b['hashes'] for b in buckets)
 condition='代码路径条件符合；真实SQL回归受权限限制'
 note='可信命中免归档SQL；缺失/过期/变更回源；业务无变化不等于元数据无写入'
 if not buckets: note='当前无对应摘要缓存；首次或冷缓存归档需SQL，热缓存实测未完成'
 if any(b['hashes']>=live['limit'] for b in buckets):note='缓存已达10000键上限；旧键淘汰后需SQL；当前命中率未测'
 if ident.startswith('ths-yuanhang-') and 'pool' in ident or ident in ['ths-yuanhang-sprint-limit-up']:
  note+='；盘中有效快照保存Redis，不进MySQL业务归档'
 if ident=='kaipanla-themes':note+='；采样保存在Redis，归档采样仍受当前摘要规则约束'
 files=[]
 for c in contrib:
  f=Path(inspect.getsourcefile(c.mapping if inspect.ismodule(c.mapping) else type(c.mapping))).resolve()
  files.append(str(f.relative_to(Path.cwd())).replace('\\','/'))
 rows.append(dict(id=ident,name=spec.name,family=family,granularity=keys[family],namespaces=namespaces,datasets=sorted({d for c in contrib for d in c.datasets}),
  mode=sorted({c.mode for c in contrib}),mapping_files=sorted(set(files)),cache_entries=count,cache_buckets=len(buckets),sampled=samples,valid=valid,conclusion=condition,note=note))
summary=dict(checked_at=live['checked_at'],tasks=len(rows),code_registered=len(rows),missing_cache_tasks=[r['id'] for r in rows if not r['cache_buckets']],
 capped_tasks=[r['id'] for r in rows if any(b['hashes']>=live['limit'] and b['namespace'] in r['namespaces'] for b in live['buckets'])],
 offline_tests_passed=88,integration_setup_errors=57,integration_completed=0,rows=rows)
files={f for row in rows for f in row['mapping_files']}|{'src/empire/plugins/pipeline/archive.py','src/empire/plugins/pipeline/fingerprints.py','src/empire/plugins/infra/collection_state.py','src/empire/plugins/datasets/astock.py'}
summary['source_sha256']={f:hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in sorted(files)}
Path('docs/evidence/redis-filter-audit-2026-10-29.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
lines=['# 55项采集任务 Redis 过滤逐项检查记录', '', '检查日期：2026-10-29（北京时间）。当前代码、客户端程序目录配置及生产 Redis 只读快照。', '',
'## 结论', '', '**不能概括为“Redis里存在，就全部不访问MySQL”。55项均登记到统一摘要归档体系，代码层面的条件路径符合；但本轮未完成逐项真实MySQL验收，不能标为55项全部实测通过。**', '',
'- 完整可信摘要命中：统一归档器跳过 MySQL，包括业务表及 collection_state；只确认Redis摘要、运行进度及删除相应待归档消息。',
'- 内容变化、摘要缺失/损坏/过期/淘汰或覆盖证明变化：回源SQL核对，必要时写入。相同业务内容不应重复业务DML，但SQL状态、覆盖或版本元数据仍可能更新。',
'- “无需归档SQL”不是“整个采集任务零SQL”：股票/日期名单、补缺规划、身份及查询、缺失Redis归档进度回源仍可能读取MySQL。',
'- Redis的纯内存策略降低持久化写入；本次未修改配置，也未测量物理磁盘写入或磁盘寿命，不能把SQL次数直接等同磁盘损坏。', '',
'## 实际验证范围', '',
f"- 正式Redis只读采样：{len(live['buckets'])}个摘要桶，共检查{sum(b['sample_size'] for b in live['buckets'])}个键的摘要结构、版本及有效期，{sum(b['valid_sample'] for b in live['buckets'])}个通过。未改写或刷新缓存，不是全量摘要正确性审计，也未将摘要和MySQL正文逐条比较。",
f"- 配置：TTL {live['ttl']}秒（7天），每数据集/来源上限{live['limit']}键。统计为顺序读取时点快照，不是跨全部数据集的原子快照。",
'- 离线测试：88通过。覆盖可信命中/迟到旧版本不调用SQL、混合批次只把未命中键交SQL、空证明回源、SQL失败不缓存、缓存确认失败不伪报成功、版本异常及队列规则。该结果验证公共分支，不能替代每个业务数据集的真实SQL集成。',
'- 选取的57个参数化集成用例全部在测试库创建阶段被MySQL权限拒绝，实际执行成功0项；并非57个业务断言失败。未更改权限，未降级到生产业务表运行测试，未清理任何生产数据或缓存。现有用例覆盖热/冷缓存、重复、修订、旧响应和清队，但本轮执行受限。', '',
'## 逐项记录', '',
'每行“条件符合”指已检查实际登记、摘要计划/子集与共享归档分支；所有行的真实SQL验收状态均为“受权限限制，未完成”。缓存数量是相关共享桶数量，不能理解为此项目已采集条数。', '',
'|序号|采集项目|摘要粒度|Redis摘要键数 / 抽样有效|结论与限制|', '|---|---|---|---|---|']
for i,r in enumerate(rows,1):
 cache=f"{r['cache_entries']} / {r['valid']}/{r['sampled']}" if r['cache_buckets'] else '未发现摘要桶 / 未抽样'
 lines.append(f"|{i}|{r['name']} `{r['id']}`|{r['granularity']}|{cache}|条件符合；{r['note']}|")
lines += ['', '## 特别需要保留的边界', '',
'1. **达到缓存上限**：远航历史行情与权息股本共用 ths_yuanhang_history_v2，已达10000键；历史涨跌停原因 yuanhang_limits_reason_v1 也已达10000键。这不绕过缓存，但会使较旧键被淘汰，后续产生SQL回源。未测命中率，不宣称上限已经造成具体磁盘负担。',
'2. **开盘啦七类行情**：当前未发现对应缓存桶；有过滤契约不等于已存在可信缓存，首次入库或缓存丢失后的回源是正常行为。',
'3. **空摘要计划**：公共入口对空plan明确回源SQL，不能把“没有任何摘要键”当作命中。当前新闻空页属于适用场景；其他来源合法空集合大多有月份/覆盖/单元摘要。',
'4. **完整范围证明**：财报、资本运作、业绩、解禁等有范围证明；即使业务行相同，范围或来源版本发生有效变化也可能需要SQL状态更新。停复牌新增来源日期覆盖同样不是可丢弃的重复。',
'5. **纯Redis盘中采样**：远航五池盘中快照经正式volatile入口保存Redis，不进入MySQL业务归档；这不保证采样前的交易日历/身份查询也完全不读SQL。',
'6. **成功清队与异常**：_archive_data完成后，增量和聚合流程均调用acknowledge；摘要命中、SQL确认相同、旧版本无需写入均能走成功清理。SQL或缓存确认抛错则不进入成功清队。这里讨论已校验有效业务；无效消息隔离/诊断路径另外处理。', '',
'## 证据入口与复核方式', '',
'- [逐项机器记录及源码摘要](redis-filter-audit-2026-10-29.json)',
'- [生产Redis只读快照](redis-filter-live-2026-10-29.json)',
'- [拟执行集成用例清单](redis-filter-audit-tests-2026-10-29.json)',
'- 公共分支：src/empire/plugins/pipeline/archive.py 的 _archive_data、_flush_incremental、_flush_aggregate；信任条件：fingerprints.py 的 _decode 与 Redis TIME/expiry 校验；登记入口：plugins/datasets/astock.py。',
'- 新增审计测试：tests/test_archive_filter_audit.py；既有版本与队列回归：tests/test_fingerprint_versions.py、tests/test_archive_queue.py。',
'- 后续若要形成“55项全部真实SQL验收通过”的结论，需提供具有创建/删除独立测试库权限的测试连接，重新执行列表中的隔离集成用例，并补齐未覆盖的分支；不能使用生产业务表替代隔离测试。', '',
'本次仅检查与生成审计证据，未改动过滤/采集/归档实现，未改变摘要容量和有效期，未操作生产业务数据。']
Path('docs/redis-filter-audit-2026-10-29.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in summary.items() if k not in ('rows','source_sha256')},ensure_ascii=False))
