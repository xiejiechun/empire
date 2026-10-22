"""Independent bounded, production read-only cross-batch acceptance; no collectors."""
import asyncio, hashlib, json, subprocess, sys
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.features.repurchases.contract import digest
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'AGENTS.md').is_file())
sys.path.insert(0,str(ROOT))
from scripts.release_identity import tree_inventory
OUT=Path(__file__).parent
@event.listens_for(Engine,'before_cursor_execute')
def guard(conn,cursor,statement,params,context,many):
    if statement.lstrip().split()[0].upper() not in {'SELECT','SHOW','START','ROLLBACK'}:
        raise RuntimeError('Read-only audit rejects SQL mutation')
def command(args):
    p=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,encoding='utf8',errors='replace')
    return dict(command=args,exit_code=p.returncode,stdout=p.stdout.strip(),stderr=p.stderr.strip())
async def main():
    r=dict(at=datetime.now(UTC).isoformat(),label=sys.argv[1])
    r['git']=[command(a) for a in [
        ['git','rev-parse','HEAD'],['git','ls-remote','origin','refs/heads/main'],
        ['git','diff','--name-only','6808f85','--','src','scripts','tests','sql','Empire.spec','verify-release.ps1']]]
    r['process']=command(['powershell.exe','-NoProfile','-Command',
        'Get-Process Empire -ErrorAction SilentlyContinue | Select-Object Id,Path,StartTime,@{N="Threads";E={$_.Threads.Count}},MainWindowTitle | ConvertTo-Json -Compress'])
    j=json.loads((ROOT/'build/releases/3892410b3e6a48858002a318bee648d5/publication.json').read_text('utf8'))
    r['release']=dict(id=j['release_id'] if 'release_id' in j else '3892410b3e6a48858002a318bee648d5',manifest=j['manifest'],state=j['state'],passed=j['passed'])
    r['exe_sha256']=hashlib.sha256((ROOT/'dist/Empire/Empire.exe').read_bytes()).hexdigest()
    r['tree_sha256']=tree_inventory(ROOT/'dist/Empire')['sha256']
    assert r['exe_sha256']==j['executable_sha256'] and r['tree_sha256']==j['candidate_sha256']
    r['preserved_inputs']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'config.toml',ROOT/'dist/Empire/config.toml',Path.home()/'AppData/Local/Empire/plugin-state.json']}
    m=build_manager(load_config(ROOT/'config.toml'))
    try:
        for ident in ['infra.redis','data.repurchases','data.kaipanla_quote','data.dividends','collection.records']:
            await m.start(ident)
        q=m.registry.get('repurchases.query');d=m.registry.get('dividends.query');store=m.registry.get('redis.store')
        with q.mysql.read_engine.connect() as c:
            c.exec_driver_sql('START TRANSACTION READ ONLY')
            r['server_uuid']=c.exec_driver_sql('SELECT @@server_uuid').scalar_one()
            settings=[dict(x) for x in c.execute(text('SELECT kind,setting_key,payload FROM app_setting WHERE namespace=:ns ORDER BY kind,setting_key'),dict(ns=store.prefix)).mappings()]
            r['settings']=dict(count=len(settings),digest=digest(settings))
            r['calendar_cutoff']=[dict(x) for x in c.execute(text("SELECT trade_date,is_trade FROM trade_calendar WHERE trade_date BETWEEN '2026-10-17' AND '2026-10-20' ORDER BY trade_date")).mappings()]
            # Formal decoder/list query is independent of the summary and yield calculator.
            quote=m.registry.get('kaipanla_quote.query')
            r['oracle_quote']=list(quote.iter_validated_days(c,'SZ','000001',__import__('datetime').date(2026,10,20),__import__('datetime').date(2026,10,20)))
            r['oracle_price_heads']=[dict(x) for x in c.execute(text("SELECT unified_code,trade_date,version_observed_at,content_hash FROM stock_market_day WHERE kind='quote' AND unified_code='000001.SZ' AND trade_date='2026-10-20'")).mappings()]
            r['oracle_snapshot_dividends']=[dict(x) for x in c.execute(text("SELECT record_key,unified_code,payload,version_observed_at FROM dividend_plan WHERE unified_code='000001.SZ' ORDER BY record_key")).mappings()]
            c.rollback()
        r['repurchase_audit']=await q.mysql.read(q.audit)
        scope=dict(codes=['000001'],start='2026-01-01',end='2026-10-20')
        r['repurchase_checks']=[vars(e) for e in await q.preparation_check(scope)]
        r['repurchase_000001']=await q.list_plans(code='000001.SZ')
        r['repurchase_600579']=await q.detail('15721')
        r['oracle_dividends']=await d.list_events(code='000001',market='SZ',limit=500)
        # Hand selected on raw status/date fields, no call to event_rules or amount/yield helpers.
        r['cases']={}
        for name,request in [('main',scope),('600000',{**scope,'codes':['600000']}),('002731',{**scope,'codes':['002731']}),('600938',{**scope,'codes':['600938']}),('historical',{**scope,'purpose':'historical_signal'}),
            *[(end,{**scope,'end':end}) for end in ['2026-06-11','2026-06-12','2026-09-23','2026-09-24','2026-10-18']],('main-again',scope)]:
            r['cases'][name]=dict(distribution=await d.distribution_summary(request),yield_result=await d.dividend_yield(request))
        r['B4_id_preserved']=await m.registry.get('collection.records').get_error('tdx-suspensions','38622b7215a44fe4a5224031bdf4d963') is not None
        r['pending']=await store.client.xlen(store.stream)
    finally:
        await m.shutdown()
    (OUT/(sys.argv[1]+'.json')).write_text(json.dumps(r,ensure_ascii=False,indent=2,default=str),encoding='utf8')
    print(json.dumps(dict(at=r['at'],repurchase={k:r['repurchase_audit'][k] for k in ['count','valid','invalid']},pending=r['pending'],cases={k:{p:v[p]['state'] for p in v} for k,v in r['cases'].items()}),ensure_ascii=False))
asyncio.run(main())
