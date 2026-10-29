from pathlib import Path
import json,re,hashlib,zipfile,ast
root=Path.cwd().resolve()
def edit(p,fn):
 p=root/p;p.write_text(fn(p.read_text('utf8')),encoding='utf8')
def remove(p):
 p=(root/p).resolve();assert p.is_relative_to(root)
 if not p.is_file():return
 with zipfile.ZipFile(root/'build/retired-kaipanla-source.zip','a',zipfile.ZIP_DEFLATED) as z:z.write(p,str(p.relative_to(root)))
 p.unlink()
old=json.loads((root/'sql/business-schema.json').read_text('utf8'))
datasets={k for k in old['dataset_table_groups'] if k.startswith('kaipanla.') and not k.startswith('kaipanla.themes.')}
tables={t for d in datasets for t in old['dataset_table_groups'][d]}
(root/'build/retired-kaipanla-objects.json').write_text(json.dumps(dict(datasets=sorted(datasets),tables=sorted(tables)),indent=2),encoding='utf8')
for key,value in old.items():
 if isinstance(value,dict):old[key]={k:v for k,v in value.items() if k not in datasets|tables}
 if isinstance(value,list):old[key]=[v for v in value if v not in tables]
(root/'sql/business-schema.json').write_text(json.dumps(old,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
edit('sql/schema.sql',lambda s:re.sub(r'CREATE TABLE IF NOT EXISTS (\w+)\s*\([\s\S]*?;',lambda m:'' if m[1] in tables else m[0],s))
p=root/'sql/schema-contract.json';m=json.loads(p.read_text('utf8'));m['tables']={k:v for k,v in m['tables'].items() if k not in tables};m['schema_sha256']=hashlib.sha256((root/'sql/schema.sql').read_bytes()).hexdigest();p.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
p=root/'docs/database-design-cards.json';m=json.loads(p.read_text('utf8'));m['datasets']={k:v for k,v in m['datasets'].items() if k not in datasets};p.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
edit('scripts/verify_documentation.py',lambda s:re.sub(r'[\"\'](?:'+ '|'.join(tables) +r')[\"\'],?\s*','',s))
edit('scripts/business_migration_inventory.py',lambda s:s.replace('from empire.features.kaipanla.storage_contract import MARKET_TABLES', 'MARKET_TABLES = '+repr(tuple(sorted(tables)))))
# Retired product-only tools and tests. Common tests are edited below.
for name in ('configure_kaipanla_task_defaults','market_migration','kaipanla_verification','kaipanla_measure_support','measure_preview_queries','measure_market_storage','measure_kaipanla_day','migrate_kaipanla_products','smoke_kaipanla_storage_sql','verify_kaipanla','migrate_market_storage'):
 remove(Path('scripts')/(name+'.py'))
for name in ('test_kaipanla_products_archive','test_intraday_archive','test_kaipanla_suspension_scope','test_market_storage','test_preview_queries','dividend_fixture','test_dividend_yield_pipeline'):
 remove(Path('tests/integration')/(name+'.py'))
for name in ('test_intraday_ui','test_kaipanla_intraday','test_kaipanla_products','test_kaipanla_public_inputs','test_kaipanla_quote_ui','test_kaipanla_source','test_kaipanla_selection','test_kaipanla_task_rules','test_market_mapping','test_preview_candidate_activation'):
 remove(Path('tests')/(name+'.py'))
edit('tests/test_business_schema_contract.py',lambda s:re.sub(r'from empire.features.kaipanla.*\n','',s).replace('                                    *(ProductDataset(kind) for kind in PRODUCTS),\n',''))
edit('tests/test_collection_rules.py',lambda s:re.sub(r'    from empire.features.kaipanla.*\n','',s))
edit('tests/test_collection_rules.py',lambda s:re.sub(r'    for kind in PRODUCTS:.*?(?=\n\ndef test_render)', '',s,flags=re.S))
edit('tests/test_listing_scope_prefetch.py',lambda s:s.replace('from empire.features.kaipanla.dates import required_days\n','').replace("project_id='kaipanla-quote'","project_id='test-listing-scope'"))
edit('tests/test_listing_scope_prefetch.py',lambda s:re.sub(r'    assert required_days.*\n','',s))
# Remove only the two retired page tests; keep unrelated chart and preview regressions.
p=root/'tests/test_preview_redesign.py';s=p.read_text('utf8');lines=s.splitlines(True)
for n in sorted(ast.parse(s).body,key=lambda n:n.lineno,reverse=True):
 if isinstance(n,ast.FunctionDef) and n.name in {'test_whole_day_contains_afternoon_and_inspection_follows_original_point','test_sequence_axis_keeps_same_minute_auction_without_inventing_seconds'}:
  start=min([n.lineno]+[d.lineno for d in n.decorator_list]);del lines[start-1:n.end_lineno]
s=''.join(lines);s=re.sub(r'from (?:empire.features.kaipanla|tests.test_kaipanla_products).*\n','',s);p.write_text(s,encoding='utf8')
edit('src/empire/features/data_browser/catalog.py',lambda s:re.sub(r"'kaipanla_\w+': '[^']+',?",'',s))
print('retired datasets',len(datasets),'tables',len(tables))
