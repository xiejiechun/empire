import asyncio, json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from sqlalchemy import event
from sqlalchemy.engine import Engine
from empire.bootstrap import build_manager
from empire.core.config import load_config

ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).parent
@event.listens_for(Engine,'before_cursor_execute')
def guard(conn,cursor,statement,params,context,many):
    if statement.lstrip().split()[0].upper() not in {'SELECT','SHOW','START','ROLLBACK'}:
        raise RuntimeError('Read-only dependency audit refuses mutation')
async def main():
    m=build_manager(load_config(ROOT/'config.toml'));r=dict(at=datetime.now(UTC).isoformat())
    scope=dict(codes=['000001'],start='2026-01-01',end='2026-10-20')
    try:
        await m.start('data.repurchases');q=m.registry.get('repurchases.query')
        assert q.context.optional('redis.store') is None
        r['sql_only']=[vars(e) for e in await q.preparation_check(scope)]
        r['historical']=[vars(e) for e in await q.preparation_check({**scope,'purpose':'historical_signal'})]
        context=q.context
        q.context=SimpleNamespace(optional=lambda _:SimpleNamespace(checkpoint=AsyncMock(side_effect=ConnectionError('injected optional Redis failure'))))
        try:r['injected_redis_unavailable']=[vars(e) for e in await q.preparation_check(scope)]
        finally:q.context=context
        r['sql_proof']=await q.mysql.read(q.audit)
        await m.start('data.kaipanla_quote');await m.start('data.dividends')
        d=m.registry.get('dividends.query')
        r['distribution']=await d.distribution_summary(scope)
        r['yield']=await d.dividend_yield(scope)
        r['600938']=await d.dividend_yield({**scope,'codes':['600938']})
        r['dividend_historical']=await d.dividend_yield({**scope,'purpose':'historical_signal'})
        await m.start('collection.records');records=m.registry.get('collection.records')
        r['B4_exact_id_preserved']=await records.get_error('tdx-suspensions','38622b7215a44fe4a5224031bdf4d963') is not None
    finally:await m.shutdown()
    with (OUT/'dependencies.json').open('x',encoding='utf8') as f:json.dump(r,f,ensure_ascii=False,indent=2,default=str)
    assert all(e['status']=='pass' for e in r['sql_only'] if e['criterion']!='temporal')
    assert r['injected_redis_unavailable']==r['sql_only']
    assert r['historical'][-1]['blocking'] is True and r['historical'][-1]['status']=='fail'
    assert r['distribution']['state']==r['yield']['state']=='已计算'
    assert r['600938']['state']=='数据阻断' and r['dividend_historical']['state']=='来源受限'
    assert r['B4_exact_id_preserved']
    print(dict(sql_fallback=True,distribution=r['distribution']['state'],yield_state=r['yield']['state'],fixed_600938=r['600938']['state'],B4_preserved=r['B4_exact_id_preserved']))
asyncio.run(main())
