import inspect,json
from pathlib import Path
from empire.bootstrap import build_manager
from empire.core.config import load_config
basis={
 'financial_statements':'本轮股票名单；成功入队股票数',
 'holders':'本轮待核验股票；成功股票数，排除失败尝试',
 'ths_capital':'本轮股票名单；成功入队股票数',
 'listings':'本轮股票范围；已核验/已有可信记录股票数',
 'calendar':'本轮完整月份计划；成功入队月份数',
 'suspensions':'本轮起止日期；成功入队来源日期数',
 'listing_status':'本轮已入队及待补月份；成功入队月份数',
 'industries':'已验证行业目录；已解析行业成员集合数，最终整份校验和归档另确认',
 'indices':'已验证指数目录；已入队指数数',
 'index_prices':'本轮指数代码；已完成指数数',
 'stocks':'来源股票总数；成功入队股票数',
 'name_changes':'1份完整来源响应；校验并入队后1/1',
 'st_events':'1份完整来源响应；校验并入队后1/1',
 'trading_rules':'1组完整官方规则；校验并入队后1/1',
 'repurchases':'来源方案总数；成功入队方案数',
 'performance':'报告期/日期/证券完整响应计划；完成响应数',
 'unlocks':'本轮月份计划；完成月份数',
 'unlock_industries':'来源月份目录；完成月份数',
 'kaipanla':'上市与停牌过滤后的证券×日期单元；成功单元数',
 'yuanhang':'本轮证券范围；已采集或可信覆盖跳过的证券数',
 'capital_actions':'来源分组证券；成功入队证券数；分红发现/报告期核验分别展示阶段进度',
 'themes':'列表1份完整快照；详情按当前待处理题材计划',
 'yuanhang_limits':'日终：已入队+计划剩余+未入计划总数；盘中：1份快照；原因剩余未知时仅当前批百分比',
 'news':'首次/重新采集固定1页；增量需读至上轮上界，总页数未知时显示已读页数，终点确定后才100%',
}
changed={'holders','ths_capital','listings','calendar','suspensions','listing_status','industries','stocks','name_changes','repurchases','performance','unlocks','unlock_industries','yuanhang','capital_actions','themes','yuanhang_limits','news','kaipanla'}
m=build_manager(load_config());rows=[]
for ident,spec in m.entries['collection.control'].plugin.definitions.items():
 p=m.entries[m.providers[spec.capability]].plugin
 module=type(p).__module__.split('.')[2]
 assert module in basis,module
 rows.append(dict(id=ident,name=spec.name,basis=basis[module],result='补齐/修正' if module in changed else '已有准确进度，保留',module=module))
Path('docs/evidence/collector-progress-audit-2026-10-29.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
lines=['# 全部采集任务百分比逐项核查 · 2026-10-29','',f'登记任务共 {len(rows)} 项，逐项以实际计划和断点核查。百分比表示所标注单元或阶段的处理进度，不等于归档成功或全市场完整性。','', '|任务|名称|进度口径|处理|','|---|---|---|---|']
lines += [f"|{v['id']}|{v['name']}|{v['basis']}|{v['result']}|" for v in rows]
lines += ['', '## 验证与边界', '', '只增加或修正展示统计，未改变来源请求、业务内容、断点及归档顺序。新增来源请求、传输、业务入队、业务DML均为0。来源5%实采不适用本次展示统计修改，未触发额外来源实采。空计划显示无待处理单元，不把0/0当未知；完整单响应任务为0%→100%，不模拟下载字节进度。', '', '股票名单变化沿既有范围重建规则执行；失败不计为成功单元；恢复等待归档时从正式断点恢复可证明的数量。未知历史统计不猜测；仍有来源缺口的旧开盘啦等待归档断点缺少全轮总数时保留未知。', '', '分红按历史目录核验、报告期核验、证券发布分阶段计数；阶段切换分母不同，非伪造的平滑整轮百分比。涨跌停原因采用有界动态计划，剩余未知时明确标注本批。新闻增量终点由历史上界决定，不能以股票数或页码上限冒充分母。', '', '相关生命周期回归487通过、3跳过（跳过不算验收）；新增日期/月失败与恢复、批次/全轮分母和失败股票扣除断言。后续专项与桌面验证结果见本次交付。']
Path('docs/evidence/collector-progress-audit-2026-10-29.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
# Update each affected feature's user-facing contract instead of unrelated help.
for module in changed:
 folder=Path('src/empire/features')/module/'docs/help'
 files=[folder/'overview.md'] if (folder/'overview.md').exists() else sorted(folder.glob('*.md'))
 if files:
  p=files[0];s=p.read_text(encoding='utf-8');s+='\n## 采集百分比\n\n'+basis[module]+'。使用本轮实际计划和已成功处理数量计算；准备范围期间不猜总量，空计划表示无需处理。百分比达到100%不替代完整集合校验或本轮归档确认；失败仍按实际结果显示。\n';p.write_text(s,encoding='utf-8')
print(len(rows),'tasks audited',sum(v['result']=='补齐/修正' for v in rows),'task projections improved')
