"""Remeasure typed theme storage on an independently owned SQL instance."""
import argparse
import asyncio
import copy
import hashlib
import json
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from capacity_session import CapacitySession
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.features.themes.history_model import digest
from empire.features.themes.repository import replace_daily, replace_detail
from empire.plugins.infra.mysql_store import initialize_database
from empire.plugins.infra.redis_store import create_client


def p95(values):
    return sorted(values)[max(0, int(len(values) * .95) - 1)]


async def queries(cfg, database, run_id):
    cfg = copy.deepcopy(cfg)
    cfg['mysql'] = database
    cfg['redis']['namespace'] = 'empire:test:theme-capacity:' + run_id
    manager = build_manager(cfg)
    try:
        await manager.start('data.themes')
        query = manager.registry.get('themes.query')
        timings = {}
        for name, method, args in [('daily', query.daily, ('2026-10-01',)),
                                    ('detail', query.detail_page, ('1',))]:
            values = []
            for _ in range(30):
                started = time.perf_counter()
                result = await method(*args)
                values.append((time.perf_counter() - started) * 1000)
                assert len(result['rows']) == 200 and result['next']
            timings[name + '_query_p95_ms'] = p95(values)
        return timings
    finally:
        await manager.shutdown()
        client = create_client(cfg['redis'])
        try:
            keys = [key async for key in client.scan_iter(match=cfg['redis']['namespace'] + ':*')]
            if keys:
                await client.delete(*keys)
        finally:
            await client.aclose()


def detail(theme_id):
    relations = []
    for index in range(1000):
        row = dict(category_id='1', source_stock_id='600001', reason='' if index == 0 else '来源理由' + str(index),
                   first_shelved_at=None, updated_at=None, is_new=0, is_hot=0, source_is_zz=0)
        relations.append(dict(row, relation_id=digest(row), occurrences=1))
    return dict(theme_id=theme_id, name='合成题材', brief='', introduction='',
                source_created_at=None, source_updated_at=None,
                categories=[dict(category_id='1', parent_id=None, name='合成分类', order=0, plate_code='',
                                 first_shelved_at=None, updated_at=None, is_new=0)],
                stocks=[dict(source_stock_id='600001', name='合成企业', unified_code='600001.SH')],
                relations=sorted(relations, key=lambda row: row['relation_id']))


def run(args):
    root, cfg = Path(__file__).resolve().parents[1], load_config()
    previous = json.loads((root / 'docs/evidence/kaipanla-theme-capacity-2026-10-24.json').read_text('utf8'))
    # History implementation is unchanged. Reuse its measured seven-day scope
    # explicitly, rather than pretending those numbers were remeasured here.
    for path in ('src/empire/features/themes/history.py', 'src/empire/features/themes/history_model.py'):
        assert hashlib.sha256((root / path).read_bytes()).hexdigest() == previous['bindings'][path]
    settings = json.loads(Path(args.test_mysql).read_text('utf8'))
    paths = [*previous['bindings'], 'scripts/measure_theme_capacity.py', 'src/empire/sources/security_identity.py']
    with CapacitySession(cfg['mysql'], settings, root=root, subject='preview', output=args.output,
                         input_paths=paths) as session:
        initialize_database(session.settings)
        observed = datetime.now(UTC)
        rows = [dict(theme_id=str(index), source_theme_id=str(index), concept_id=None, name='合成题材' + str(index),
                     parent_id=None, new_flag=0, rank_no=index, display_order=index - 1, hot_score='100',
                     change_rate='1.25', limit_up_count=1) for index in range(1, 2001)]
        started = time.perf_counter()
        for offset in range(30):
            with session.engine.begin() as conn:
                assert replace_daily(conn, (date(2026, 10, 1) + timedelta(days=offset)).isoformat(), rows, observed) == 2000
        list_seconds = time.perf_counter() - started
        started = time.perf_counter()
        for index in range(1, 31):
            with session.engine.begin() as conn:
                assert replace_detail(conn, detail(str(index)), observed) == 1003
        detail_seconds = time.perf_counter() - started
        dml = []
        def track(conn, cursor, statement, parameters, context, many):
            if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
                dml.append(statement.split()[0])
        event.listen(session.engine, 'before_cursor_execute', track)
        started = time.perf_counter()
        with session.engine.begin() as conn:
            assert replace_daily(conn, '2026-10-01', rows, observed) == 0
            assert replace_detail(conn, detail('1'), observed) == 0
        repeat_ms = (time.perf_counter() - started) * 1000
        assert not dml
        event.remove(session.engine, 'before_cursor_execute', track)
        with session.engine.connect() as conn:
            counts = {table: conn.execute(text('SELECT COUNT(*) FROM ' + table)).scalar_one()
                      for table in ('theme_daily', 'theme_detail', 'theme_stock_reason')}
        assert counts == dict(theme_daily=60000, theme_detail=30, theme_stock_reason=30000)
        report = session.report
        report.update(bindings=session.frozen_inputs, ddl_scopes=previous['ddl_scopes'], limits=previous['limits'],
                      measurements={**previous['history'], 'daily_rows': 60000, 'detail_units': 30, 'relation_rows': 30000,
                                    'list_write_seconds': list_seconds, 'detail_write_seconds': detail_seconds,
                                    'unchanged_list_and_detail_ms': repeat_ms,
                                    **asyncio.run(queries(cfg, session.settings, session.run_id))},
                      history=previous['history'],
                      conditions={'history': 'Reused unchanged history implementation and 2026-10-24 seven-day measurement',
                                  'sql': 'Current typed repository and official paginated query; synthetic 60000 daily rows and 30000 relations including empty reasons'},
                      reviewed_tradeoffs=previous['reviewed_tradeoffs'],
                      unchanged_business_dml=0, exact_counts=counts,
                      reused_history_evidence='docs/evidence/kaipanla-theme-capacity-2026-10-24.json')
        assert all(report['measurements'][key] <= maximum for key, maximum in report['limits'].items())
        session.measurements_complete = True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-mysql', required=True)
    parser.add_argument('--output', required=True)
    run(parser.parse_args())
