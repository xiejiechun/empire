import asyncio, hashlib, json, re, sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from PySide6.QtCore import QCoreApplication
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from repurchase_verification import verify_scope
from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.core.redaction import Redactor
from empire.features.repurchases.contract import COLUMNS, PROJECT, digest, validate
from empire.plugins.infra.collection_state import read_state
from empire.features.repurchases.query import public

ROOT=Path(__file__).resolve().parents[2]; OUT=Path(__file__).parent
changes=[]
@event.listens_for(Engine,'before_cursor_execute')
def guard(conn,cursor,statement,params,context,many):
    verb=statement.lstrip().split()[0].upper()
    if verb not in {'SELECT','SHOW','START','ROLLBACK'}:
        if verb not in {'INSERT','UPDATE'} or not re.search(r'\b(?:stock_repurchase_plan|collection_state)\b',statement):
            raise RuntimeError('P3 guard rejects SQL outside formal repurchase archive')
        changes.append(dict(verb=verb,table='stock_repurchase_plan' if 'stock_repurchase_plan' in statement else 'collection_state',many=many))

def snapshot(q,namespace):
    with q.mysql.read_engine.connect() as c:
        c.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
        identity=dict(c.exec_driver_sql('SELECT @@server_uuid AS server_uuid,@@port AS port,@@transaction_isolation AS isolation').mappings().one())
        assert identity['server_uuid']=='77f9ba30-b666-11f1-81c5-380525361d4e'
        records=[dict(r) for r in c.exec_driver_sql('SELECT * FROM stock_repurchase_plan ORDER BY plan_id').mappings()]
        rows={r['plan_id']:validate({k:public(r)[k] for k in COLUMNS}) for r in records}
        state=read_state(c,namespace,PROJECT,'eastmoney')
        c.rollback()
        return rows,dict(identity=identity,state=state,members=[dict(plan_id=r['plan_id'],hash=digest(rows[r['plan_id']]),updated_date=r['updated_date'],observed=r['version_observed_at']) for r in records])

async def main():
    cfg=load_config(ROOT/'config.toml'); redactor=Redactor.from_config(cfg)
    lock=acquire_instance_lock(); manager=build_manager(cfg)
    report=dict(at=datetime.now(UTC).isoformat(),scope='one bounded production whole-source round; no scheduler',results={},errors=[])
    try:
        await manager.start('infra.redis'); await manager.start('data.repurchases')
        store=manager.registry.get('redis.store'); q=manager.registry.get('repurchases.query')
        assert await store.client.xlen(store.stream)==0
        before,report['before']=snapshot(q,store.prefix)
        report['before_preparation']=[vars(e) for e in await q.preparation_check()]
        # Starts only the declared collector and dependencies. No control/scheduler.
        await manager.start('collector.eastmoney_repurchase')
        collector=manager.registry.get('collector.eastmoney_repurchase')
        original=collector.http.request
        source={}
        async def request(*args,**kwargs):
            response=await original(*args,**kwargs)
            try:
                from decimal import Decimal
                from empire.features.repurchases.contract import parse
                after=kwargs['params'].get('filter','').split('"')[1] if 'filter' in kwargs['params'] else ''
                rows,_=parse(json.loads(response.content,parse_float=Decimal),after=after)
                for row in rows:
                    assert row['plan_id'] not in source
                    source[row['plan_id']]=row
                return response
            except BaseException:
                response.close(); raise
        collector.http.request=request
        async with asyncio.timeout(240):
            await verify_scope(manager,None,SimpleNamespace(proxy_only=True),report)
        after,report['after']=snapshot(q,store.prefix)
        report['differences']=dict(
            before_only=sorted(before.keys()-source.keys()),source_only=sorted(source.keys()-before.keys()),
            revised={key:{field:dict(before=before[key][field],source=source[key][field]) for field in COLUMNS if before[key][field]!=source[key][field]}
                     for key in sorted(before.keys()&source.keys()) if before[key]!=source[key]},
            after_only=sorted(after.keys()-source.keys()),missing_after=sorted(source.keys()-after.keys()),
            content_mismatches_after=[key for key in source.keys()&after.keys() if source[key]!=after[key]])
        report['source_members']=[dict(plan_id=key,unified_code=value['unified_code'],hash=digest(value),updated_date=value['updated_date']) for key,value in sorted(source.items())]
        report['old_keys_retained']=before.keys()<=after.keys()
        report['pending']=await store.client.xlen(store.stream)
        report['after_preparation']=[vars(e) for e in await q.preparation_check(dict(codes=['000001'],start='2026-01-01',end='2026-10-20'))]
        report['000001_all']=await q.list_plans(code='000001.SZ')
        report['000001_range']=await q.list_plans(code='000001.SZ',start='2026-01-01',end='2026-10-20')
    except BaseException as exc:
        report['errors'].append(dict(type=type(exc).__name__,message=redactor.text(exc,2048)))
    finally:
        await manager.shutdown(); lock.unlock()
        report['sql_mutations']=changes
        report['finished_at']=datetime.now(UTC).isoformat()
        with (OUT/'production-source.json').open('x',encoding='utf8') as f:json.dump(report,f,ensure_ascii=False,indent=2,default=str)
    ok=not report['errors'] and report.get('pending')==0 and report.get('old_keys_retained') is True
    print(dict(ok=ok,errors=report['errors'],differences=report.get('differences'),sql_mutations=len(changes)))
    return 0 if ok else 1
app=QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
raise SystemExit(asyncio.run(main()))
