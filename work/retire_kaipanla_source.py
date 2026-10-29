from pathlib import Path
import json,re,zipfile
root=Path.cwd().resolve()
removed=[]
def remove(p):
 p=(root/p).resolve(); assert p.is_relative_to(root) and p.is_file()
 removed.append(str(p.relative_to(root)).replace('\\','/'))
 with zipfile.ZipFile(root/'build/retired-kaipanla-source.zip','a',zipfile.ZIP_DEFLATED) as z:z.write(p,str(p.relative_to(root)))
 p.unlink()
def edit(p,fn):
 p=root/p;p.write_text(fn(p.read_text('utf8')),encoding='utf8')
package=root/'src/empire/features/kaipanla'
# Exclusive feature implementation. Preserve working changes in a local recovery archive.
for p in sorted(package.rglob('*')):
 if p.is_file() and '__pycache__' not in p.parts: remove(p.relative_to(root))
edit('src/empire/features/builtin.py',lambda s:s.replace('from empire.features.kaipanla.bundle import bundle as kaipanla_bundle\n','').replace('data_browser_bundle, kaipanla_bundle,','data_browser_bundle,'))
edit('src/empire/desktop_bridge/preview_catalog.py',lambda s:re.sub(r'    if task.startswith\("kaipanla-"\):.*?(?=    if task == "ths-yuanhang-prices")','',s,flags=re.S))
edit('src/empire/desktop_bridge/preview.py',lambda s:re.sub(r'    elif mode in \("series", "quote"\):.*?(?=    data = await method)','',s,flags=re.S))
edit('src/empire/desktop_bridge/preview.py',lambda s:re.sub(r'    if mode == "quote":\n.*?\n(?=    if isinstance)','',s,flags=re.S))
edit('src/empire/desktop_bridge/preview.py',lambda s:re.sub(r'    if mode == "series":.*?(?=    next_cursor)','',s,flags=re.S))
edit('src/empire/diagnostics/declarations.py',lambda s:s.replace('from empire.features.kaipanla.storage_contract import SERIES\n',''))
edit('src/empire/diagnostics/declarations.py',lambda s:re.sub(r'    if hasattr\(plugin, \'archived_date\'\):.*?(?=    methods =)','',s,flags=re.S))
edit('src/empire/features/data_browser/api.py',lambda s:re.sub(r'    from empire.features.kaipanla.contract import PRODUCTS.*?(?=    name_expr)',"    if dataset not in TABLES:\n        raise ValueError('未登记的证券候选数据集')\n    table, name = TABLES[dataset]\n",s,flags=re.S))
edit('src/empire/features/data_browser/api.py',lambda s:re.sub(r'    if product:.*?    elif dataset.startswith', '    if dataset.startswith',s,flags=re.S))
edit('src/empire/features/data_browser/api.py',lambda s:re.sub(r'            if product:.*?(?=            rows = conn.execute\(text\(f\'SELECT DISTINCT)', '',s,flags=re.S))
edit('src/empire/features/preparation/existing.py',lambda s:s.replace('from empire.features.kaipanla.contract import PRODUCTS\n',''))
edit('src/empire/features/preparation/existing.py',lambda s:s[:s.index('    *(R(item.requirement')]+'''    R('historical_quote', '历史收盘价格与股本快照', '股票行情', '核心',
      '区间估值所需输入', '证券 × 交易日', '收盘价及同日股本', '证券 + 日期',
      '明确来源和日期范围', '价格和股本单位一致', '按来源更新', '只使用已结束交易日',
      boundary='原开盘啦行情功能已移除，本项暂无已登记提供者；远航日线不冒充盘口股本快照。'),
)
''')
# Preserve the user-facing calculation contract but fail explicitly before any SQL.
edit('src/empire/features/capital_actions/dividend_yield.py',lambda s:'''"""Explicit unavailable result after retirement of the required quote provider."""
from dataclasses import asdict
from empire.contracts.preparation import CheckEvidence
from empire.contracts.preparation_scope import PreparationScope

PROBLEM = '开盘啦历史盘口功能已移除，缺少收盘价及逐日股本快照输入，区间现金股息率暂不可计算。'

async def calculate_yield(plugin, request):
    PreparationScope.parse(request)
    return dict(id='dividend_yield', title='区间名义现金股息率', state='数据阻断',
                problem=PROBLEM, securities=[], checks=[asdict(CheckEvidence('fields', 'fail', PROBLEM))])

async def preparation_check(plugin, request=None):
    return (CheckEvidence('fields', 'fail', PROBLEM),)
''')
remove(Path('src/empire/features/capital_actions/yield_inputs.py'))
edit('src/empire/features/capital_actions/query.py',lambda s:s.replace('通达信分红 / 巨潮日历 / 开盘啦未复权收盘价','区间现金股息率（缺少价格及股本输入）'))
# Registered collection rules: exact seven IDs only.
p=root/'src/empire/plugins/collection/rules.json'; rules=json.loads(p.read_text('utf8'))
ids=['kaipanla-'+k for k in ('trend','auction','volume','trades','entrust','large-order','quote')]
for key in ids: rules['tasks'].pop(key,None)
p.write_text(json.dumps(rules,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
(root/'build/kaipanla-retirement-files.json').write_text(json.dumps(removed,ensure_ascii=False,indent=2),encoding='utf8')
print('removed exclusive source files',len(removed))
