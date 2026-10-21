import asyncio,json,hashlib,os,sys
from pathlib import Path
from datetime import UTC,datetime
from sqlalchemy import text
from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client,RedisPlugin
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from scripts.release_identity import tree_inventory
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
async def main():
    cfg=load_config(ROOT/'config.toml');before=json.loads((OUT/'preflight.json').read_text('utf8'))
    journal=json.loads((ROOT/'build/releases/4c672429732f48669159d410a91917d9/publication.json').read_text('utf8'))
    report=dict(at=datetime.now(UTC).isoformat(),release={k:journal.get(k) for k in ['run_id','state','passed','executable_sha256','candidate_sha256']})
    report['exe_matches']=sha(ROOT/'dist/Empire/Empire.exe')==journal['executable_sha256']
    report['installed_tree_sha256']=tree_inventory(ROOT/'dist/Empire')['sha256']
    report['tree_matches']=report['installed_tree_sha256']==journal['candidate_sha256']
    report['preserved_inputs']={p:sha(Path(p)) for p in before['preserved_inputs']}
    report['inputs_preserved']=report['preserved_inputs']==before['preserved_inputs']
    engine=make_engine(cfg['mysql'],pool_size=1)
    try:
        with engine.connect() as c:
            c.exec_driver_sql('START TRANSACTION READ ONLY')
            report['server_uuid']=c.exec_driver_sql('SELECT @@server_uuid').scalar_one()
            rows=[dict(r) for r in c.execute(text('SELECT kind,setting_key,payload FROM app_setting WHERE namespace=:ns ORDER BY kind,setting_key'),dict(ns=cfg['redis']['namespace'])).mappings()]
            c.rollback()
    finally:engine.dispose()
    report['production_server_preserved']=report['server_uuid']==before['production_mysql']['server_uuid']
    report['settings_count']=len(rows);report['settings_digest']=hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
    report['settings_preserved']=report['settings_count']==before['settings_count'] and report['settings_digest']==before['settings_digest']
    client=create_client(cfg['redis']);store=RedisPlugin(cfg['redis'])
    try:
        report['global_pending']=await client.xlen(store.stream)
    finally:await client.aclose()
    manager=build_manager(cfg)
    try:
        await manager.start('infra.redis')
        await manager.start('data.kaipanla_quote')
        await manager.start('data.dividends')
        dividend_query=manager.registry.get('dividends.query')
        scope=dict(codes=['000001'],start='2026-01-01',end='2026-10-20')
        report['fixed_nominal']=await dividend_query.distribution_summary(scope)
        report['fixed_yield']=await dividend_query.dividend_yield(scope)
        report['blocked_history']=await dividend_query.dividend_yield({**scope,'codes':['600938']})
        report['historical_signal']=await dividend_query.dividend_yield({**scope,'purpose':'historical_signal'})
        await manager.start('data.suspensions');q=manager.registry.get('suspensions.query')
        report['suspension_fixed_queries']={d:await q.list_events(code='603517',start=d,end=d) for d in ['2026-10-19','2026-10-20']}
        await manager.start('data.bond_holders');q=manager.registry.get('bond_holders.query')
        report['holder_fixed_queries']={code:await q.browse(code=code,start=d,end=d) for code,d in [('300398.SZ','2023-12-31'),('601515.SH','2024-06-30')]}
        await manager.start('collection.records');records=manager.registry.get('collection.records')
        old=await records.get_error('tdx-suspensions','38622b7215a44fe4a5224031bdf4d963')
        report['old_error_preserved']=old is not None
    finally:await manager.shutdown()
    with (OUT/(sys.argv[1]+'.json')).open('x',encoding='utf8') as f:json.dump(report,f,ensure_ascii=False,indent=2,default=str)
    assert all(report[k] for k in ['exe_matches','tree_matches','production_server_preserved','inputs_preserved','settings_preserved','old_error_preserved'])
    print({k:v for k,v in report.items() if k in ['release','exe_matches','inputs_preserved','settings_preserved','global_pending','old_error_preserved']})
asyncio.run(main())
