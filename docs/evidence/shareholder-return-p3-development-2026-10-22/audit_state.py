import asyncio, hashlib, json, os, subprocess
from datetime import UTC, datetime
from pathlib import Path
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.features.repurchases.contract import COLUMNS, JOB, PROJECT, digest, extend_digest, validate
from empire.features.repurchases.dataset import FINGERPRINT_NAMESPACE, FINGERPRINT_VERSION
from empire.plugins.infra.collection_state import read_state
from empire.plugins.pipeline.fingerprints import FingerprintCache

ROOT=Path(__file__).resolve().parents[2]; OUT=Path(__file__).parent
@event.listens_for(Engine,'before_cursor_execute')
def guard(conn,cursor,statement,params,context,many):
    if statement.lstrip().split()[0].upper() not in {'SELECT','SHOW','START','ROLLBACK'}:
        raise RuntimeError('Read-only P3 audit refuses mutation')

async def main():
    cfg=load_config(ROOT/'config.toml'); m=build_manager(cfg)
    report=dict(at=datetime.now(UTC).isoformat(),head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip())
    try:
        await m.start('infra.redis'); await m.start('data.repurchases')
        q=m.registry.get('repurchases.query'); store=m.registry.get('redis.store')
        before=await store.client.hgetall(f'{store.prefix}:checkpoint:{JOB}')
        with q.mysql.read_engine.connect() as c:
            c.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
            report['identity']=dict(c.exec_driver_sql('SELECT @@server_uuid AS server_uuid,@@port AS port,@@transaction_isolation AS isolation').mappings().one())
            assert report['identity']['server_uuid']=='77f9ba30-b666-11f1-81c5-380525361d4e'
            report['sql_state']=read_state(c,store.prefix,PROJECT,'eastmoney')
            records=[dict(r) for r in c.exec_driver_sql('SELECT * FROM stock_repurchase_plan ORDER BY plan_id').mappings()]
            rows=[validate({k:r[k] for k in COLUMNS}) for r in records]
            report['members']=[dict(plan_id=r['plan_id'],unified_code=r['unified_code'],content_hash=digest(row),stored_hash=r['content_hash'],updated_date=r['updated_date'],version_observed_at=r['version_observed_at']) for r,row in zip(records,rows)]
            report['count']=len(rows); report['digest']=extend_digest('0'*64,rows)
            settings=[dict(r) for r in c.execute(text('SELECT kind,setting_key,payload FROM app_setting WHERE namespace=:ns ORDER BY kind,setting_key'),{'ns':store.prefix}).mappings()]
            report['settings_count']=len(settings);report['settings_digest']=digest(settings)
            c.rollback()
        cache=FingerprintCache(store,cfg['archive'],lambda _:FINGERPRINT_VERSION)
        fingerprints=await cache.peek(FINGERPRINT_NAMESPACE,'eastmoney',[r['plan_id'] for r in rows])
        report['fingerprints']=fingerprints
        report['cache_count']=len(fingerprints)
        report['cache_hash_mismatches']=[r['plan_id'] for r in rows if fingerprints.get(r['plan_id'],{}).get('hash')!=digest(r)]
        report['checkpoint_before']=before
        report['checkpoint_after']=await store.client.hgetall(f'{store.prefix}:checkpoint:{JOB}')
        report['checkpoint_stable']=report['checkpoint_before']==report['checkpoint_after']
        report['pending']=await store.client.xlen(store.stream)
        report['formal_audit']=await q.mysql.read(q.audit)
        report['formal_preparation']=[vars(e) for e in await q.preparation_check(dict(codes=['000001'],start='2026-01-01',end='2026-10-20'))]
        report['formal_000001_all']=await q.list_plans(code='000001.SZ')
        report['formal_000001_range']=await q.list_plans(code='000001.SZ',start='2026-01-01',end='2026-10-20')
        paths=[ROOT/'config.toml',ROOT/'dist/empire/config.toml',Path(os.environ['LOCALAPPDATA'])/'Empire/plugin-state.json']
        report['preserved_inputs']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        report['exe_sha256']=hashlib.sha256((ROOT/'dist/empire/Empire.exe').read_bytes()).hexdigest()
    finally: await m.shutdown()
    target=OUT/(os.environ.get('P3_AUDIT_NAME','initial-state')+'.json')
    with target.open('x',encoding='utf8') as f:json.dump(report,f,ensure_ascii=False,indent=2,default=str)
    print({k:report[k] for k in ('count','digest','cache_count','cache_hash_mismatches','checkpoint_stable','pending','settings_count')})
asyncio.run(main())
