"""Formal, read-only output preservation checks; no product/O7 calculation."""
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.features.capital_actions.contract import digest

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent


@event.listens_for(Engine, 'before_cursor_execute')
def guard(conn, cursor, statement, params, context, many):
    if statement.lstrip().split()[0].upper() not in {'SELECT', 'SHOW', 'START', 'ROLLBACK'}:
        raise RuntimeError('Read-only O7 preservation check refuses mutation')


async def main():
    result = dict(started_at=datetime.now(UTC).isoformat(), source_requests=0)
    manager = build_manager(load_config(ROOT / 'config.toml'))
    try:
        for plugin in ('infra.redis', 'data.additional_issues', 'data.rights_issues',
                       'data.kaipanla_quote', 'data.dividends', 'data.repurchases', 'collection.records'):
            await manager.start(plugin)
        store = manager.registry.get('redis.store')
        result['pending_before'] = await store.client.xlen(store.stream)
        q = manager.registry.get('additional_issues.query')
        with q.mysql.read_engine.connect() as conn:
            conn.exec_driver_sql('START TRANSACTION READ ONLY')
            result['server_uuid'] = conn.exec_driver_sql('SELECT @@server_uuid').scalar_one()
            settings = [dict(r) for r in conn.execute(text('SELECT kind,setting_key,payload FROM app_setting '
                'WHERE namespace=:ns ORDER BY kind,setting_key'), dict(ns=store.prefix)).mappings()]
            conn.rollback()
        result.update(settings_count=len(settings), settings_digest=digest(settings))
        scope = dict(codes=['000001'], start='2026-01-01', end='2026-10-20')
        dividend = manager.registry.get('dividends.query')
        result['distribution'] = await dividend.distribution_summary(scope)
        result['yield'] = await dividend.dividend_yield(scope)
        result['600938'] = await dividend.distribution_summary({**scope, 'codes': ['600938']})
        result['historical_signal'] = await dividend.distribution_summary({**scope, 'purpose': 'historical_signal'})
        repurchase = manager.registry.get('repurchases.query')
        result['repurchase_preparation'] = [vars(c) for c in await repurchase.preparation_check(scope)]
        result['B4_id_present'] = await manager.registry.get('collection.records').get_error(
            'tdx-suspensions', '38622b7215a44fe4a5224031bdf4d963') is not None
        result['candidate_scope'] = dict(codes=['600590'], start='2016-01-01', end='2016-12-31')
        result['candidate_records'] = await q.list_events(code='600590', market='SH',
                                                        start='2016-01-01', end='2016-12-31')
        result['candidate_preparation'] = [vars(c) for c in await q.preparation_check(result['candidate_scope'])]
        result['candidate_historical_signal'] = [vars(c) for c in await q.preparation_check(
            {**result['candidate_scope'], 'purpose': 'historical_signal'})]
        result['pending_after'] = await store.client.xlen(store.stream)
    finally:
        await manager.shutdown()
    result['preserved_inputs'] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT / 'config.toml', ROOT / 'dist/Empire/config.toml')}
    result['exe_sha256'] = hashlib.sha256((ROOT / 'dist/Empire/Empire.exe').read_bytes()).hexdigest()
    original = json.loads((ROOT / 'docs/evidence/shareholder-return-o7-2026-10-22/input-audit.json').read_text('utf8'))
    assert result['preserved_inputs'] == original['preserved_inputs_before']
    assert result['distribution']['state'] == result['yield']['state'] == '已计算'
    assert result['distribution']['securities'][0]['cash_per_share'] == '0.609'
    assert result['600938']['state'] == '数据阻断'
    assert result['historical_signal']['state'] == '来源受限'
    assert all(c['status'] == 'pass' for c in result['repurchase_preparation'] if c['blocking'])
    assert result['B4_id_present']
    assert len(result['candidate_records']) == 1
    result['finished_at'] = datetime.now(UTC).isoformat()
    with (OUT / 'preservation.json').open('x', encoding='utf8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print('Read-only preservation checks completed; no O7 calculation asserted.')


if __name__ == '__main__':
    asyncio.run(main())
