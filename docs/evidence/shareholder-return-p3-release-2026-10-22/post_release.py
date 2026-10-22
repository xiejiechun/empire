import asyncio,hashlib,json,sys
from datetime import UTC,datetime
from pathlib import Path
from sqlalchemy import event,text
from sqlalchemy.engine import Engine
from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.features.repurchases.contract import digest
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from scripts.release_identity import tree_inventory
@event.listens_for(Engine,'before_cursor_execute')
def guard(conn,cursor,statement,params,context,many):
    if statement.lstrip().split()[0].upper() not in {'SELECT','SHOW','START','ROLLBACK'}:
        raise RuntimeError('Read-only installed package audit refuses mutation')
async def main():
    before=json.loads((OUT/'initial-state.json').read_text('utf8'))
    journal=json.loads((ROOT/'build/releases'/sys.argv[1]/'publication.json').read_text('utf8'))
    r=dict(at=datetime.now(UTC).isoformat(),release_id=sys.argv[1],manifest=journal['manifest'])
    assert journal['passed'] and journal['state']=='committed'
    r['exe_sha256']=hashlib.sha256((ROOT/'dist/Empire/Empire.exe').read_bytes()).hexdigest()
    r['exe_matches']=r['exe_sha256']==journal['executable_sha256']
    r['tree_sha256']=tree_inventory(ROOT/'dist/Empire')['sha256']
    r['tree_matches']=r['tree_sha256']==journal['candidate_sha256']
    r['preserved_inputs']={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in before['preserved_inputs']}
    r['inputs_preserved']=r['preserved_inputs']==before['preserved_inputs']
    cfg=load_config(ROOT/'config.toml');m=build_manager(cfg)
    try:
        await m.start('infra.redis');await m.start('data.repurchases')
        q=m.registry.get('repurchases.query');store=m.registry.get('redis.store')
        with q.mysql.read_engine.connect() as c:
            c.exec_driver_sql('START TRANSACTION READ ONLY')
            r['server_uuid']=c.exec_driver_sql('SELECT @@server_uuid').scalar_one()
            settings=[dict(row) for row in c.execute(text('SELECT kind,setting_key,payload FROM app_setting WHERE namespace=:ns ORDER BY kind,setting_key'),dict(ns=store.prefix)).mappings()]
            c.rollback()
        r['settings_count']=len(settings);r['settings_digest']=digest(settings)
        r['settings_preserved']=r['settings_digest']==before['settings_digest'] and len(settings)==before['settings_count']
        r['server_preserved']=r['server_uuid']==before['identity']['server_uuid']
        r['repurchase_audit']=await q.mysql.read(q.audit)
        r['repurchase_preparation']=[vars(e) for e in await q.preparation_check(dict(codes=['000001'],start='2026-01-01',end='2026-10-20'))]
        r['000001_all']=await q.list_plans(code='000001.SZ')
        r['600579_detail']=await q.detail('15721')
        await m.start('data.kaipanla_quote');await m.start('data.dividends');d=m.registry.get('dividends.query')
        scope=dict(codes=['000001'],start='2026-01-01',end='2026-10-20')
        r['distribution']=await d.distribution_summary(scope);r['yield']=await d.dividend_yield(scope)
        r['600938']=await d.dividend_yield({**scope,'codes':['600938']})
        r['historical']=await d.dividend_yield({**scope,'purpose':'historical_signal'})
        await m.start('collection.records');records=m.registry.get('collection.records')
        r['B4_id_preserved']=await records.get_error('tdx-suspensions','38622b7215a44fe4a5224031bdf4d963') is not None
        r['pending']=await store.client.xlen(store.stream)
    finally:await m.shutdown()
    with (OUT/(sys.argv[2]+'.json')).open('x',encoding='utf8') as f:json.dump(r,f,ensure_ascii=False,indent=2,default=str)
    assert all(r[k] for k in ['exe_matches','tree_matches','inputs_preserved','settings_preserved','server_preserved','B4_id_preserved'])
    assert r['repurchase_audit']['valid'] and r['pending']==0
    print({k:r[k] for k in ['release_id','exe_matches','tree_matches','inputs_preserved','settings_preserved','server_preserved','B4_id_preserved','pending']})
asyncio.run(main())
