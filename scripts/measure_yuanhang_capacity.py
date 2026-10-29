"""Synthetic native-history SQL capacity on an independently owned private server."""
import argparse
import json
import time
import tracemalloc
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from capacity_session import CapacitySession
from create_name_change_schema import ddl
from schema_evidence_scope import objects
from sqlalchemy import event, text

from empire.core.config import load_config
from empire.core.time import CHINA
from empire.features.yuanhang.contract import TABLE_COLUMNS
from empire.features.yuanhang.range_archive import write_prices
from empire.features.yuanhang.repository import (
    _save_proof,
    _upsert,
    read_heads,
    read_rows,
    replace_financial,
)
from empire.plugins.infra.collection_state_unit import read_unit, save_unit
from empire.sources.yuanhang_coverage import year_proof
from empire.sources.yuanhang_payload import CONTRACT, action_key, digest


def payload(code, year):
    first = date(year, 1, 1)
    rows = [[(first+timedelta(days=i)).isoformat(), '2', '3', '1', '2', '100', None] for i in range(250)]
    return dict(contract=CONTRACT, code=code, native_market='USZA', year=year, through=f'{year}-12-31',
                history_first=rows[0][0], history_last=rows[-1][0], history_count=250,
                rows=rows, source_count=250, key_hash=digest([r[0] for r in rows]))


def p95(values):
    return sorted(values)[max(0, int(len(values)*0.95)-1)]


def archive_year(conn, payload, observed, heads):
    head = heads[payload['year']]
    stamp = head['version_observed_at'].replace(tzinfo=CHINA).astimezone(UTC).isoformat(timespec='microseconds')
    unit = dict(price_ranges={str(payload['year']): [[f"{payload['year']}-01-01",
                head['verified_through'], stamp]]}, full_checked={})
    outcome = write_prices(conn, SimpleNamespace(observed_at=observed),
        dict(history=payload, row_count=len(payload['rows']), archive_state=dict(units={payload['code']: unit})), heads)
    return outcome['written_count']


def run(args):
    root, cfg = Path(__file__).resolve().parents[1], load_config(args.config)
    settings = json.loads(Path(args.test_mysql).read_text('utf-8'))
    paths = ['src/empire/features/yuanhang/' + n + '.py' for n in ('repository','contract','dataset','query','range_archive')]
    paths += ['src/empire/sources/yuanhang_payload.py', 'src/empire/sources/yuanhang_coverage.py']
    paths += ['src/empire/sources/yuanhang_ranges.py', 'src/empire/sources/yuanhang_range_payload.py']
    paths += ['scripts/measure_yuanhang_capacity.py', 'src/empire/plugins/infra/collection_state_unit.py']
    # Reuse the generic isolated formal-query preview scope; subject is the
    # harness category, while dataset_subject identifies these measurements.
    with CapacitySession(cfg['mysql'], settings, root=root, subject='preview', output=args.output, input_paths=paths) as session:
        engine, report = session.engine, session.report
        report['bindings'] = session.frozen_inputs
        report['dataset_subject'] = 'yuanhang'
        with engine.begin() as conn:
            for table in TABLE_COLUMNS:
                conn.exec_driver_sql(ddl(table))
            conn.exec_driver_sql(ddl('collection_state'))
        tracemalloc.start()
        started = time.perf_counter()
        observed = datetime.now(UTC)
        # 1000 securities ×4 synthetic years ×250 dates =1,000,000 typed rows.
        # Synthetic dates are sequential test dates; no trading calendar is inferred.
        for code_number in range(1000):
            code = f'{code_number:06d}.SZ'
            with engine.begin() as conn:
                for year in range(2022, 2026):
                    p = payload(code, year)
                    records = [dict(unified_code=code, **dict(zip(TABLE_COLUMNS['yuanhang_daily_price'][1:], r, strict=True)))
                               for r in p['rows']]
                    _upsert(conn, 'yuanhang_daily_price', ('unified_code','trade_date'), records)
                    _save_proof(conn, 'yuanhang_price_year', code, year_proof(p), None, observed)
        import_seconds = time.perf_counter()-started
        p = payload('000000.SZ', 2025)
        # Measure an actual changed-row archive, then repeat that same payload
        # below to prove zero business DML for unchanged content.
        p['rows'][0][-1] = '2'
        times, queries, explanations = [], {}, {}
        with engine.begin() as conn:
            t = time.perf_counter()
            archive_year(conn, p, observed+timedelta(seconds=1), read_heads(conn,p['code'],year=2025,lock=True))
            archive_ms = (time.perf_counter()-t)*1000
            for kind, sql, params in (
                ('security', 'SELECT trade_date,open,high,low,close,volume_shares,amount_yuan FROM yuanhang_daily_price '
                 'WHERE unified_code=:code AND trade_date>:after ORDER BY trade_date LIMIT 500',
                 dict(code='000000.SZ',after='2022-01-01')),
                ('cross_section', 'SELECT unified_code,trade_date,close,volume_shares,amount_yuan FROM yuanhang_daily_price '
                 'WHERE trade_date=:day AND unified_code>:after ORDER BY unified_code LIMIT 500',
                 dict(day='2025-01-01', after='')),
                ('quality', 'SELECT SUM(NOT(low<=LEAST(open,close) AND high>=GREATEST(open,close))),'
                 'SUM(amount_yuan IS NULL) FROM yuanhang_daily_price WHERE unified_code=:code',
                 dict(code='000000.SZ')),
            ):
                samples, bytes_read, count = [], 0, 0
                for _ in range(31):
                    t = time.perf_counter()
                    values = conn.execute(text(sql), params).all()
                    samples.append((time.perf_counter()-t)*1000)
                    bytes_read = len(json.dumps([list(r) for r in values],default=str).encode())
                    count = len(values)
                queries[kind] = dict(first_query_ms=samples[0], warm_p95_ms=p95(samples[1:]), rows=count, encoded_bytes=bytes_read)
                explanations[kind] = [dict(r) for r in conn.execute(text('EXPLAIN '+sql),params).mappings()]
            for _ in range(20):
                t = time.perf_counter()
                rows = read_rows(conn, '000000.SZ', 'prices', year=2025)
                assert digest(rows) == digest(p['rows'])
                times.append((time.perf_counter()-t)*1000)
        dml = []
        def count_dml(conn, cursor, statement, *args):
            if statement.startswith(('INSERT INTO yuanhang_', 'DELETE FROM yuanhang_', 'UPDATE yuanhang_')):
                dml.append(statement)
        event.listen(engine, 'before_cursor_execute', count_dml)
        try:
            with engine.begin() as conn:
                heads = read_heads(conn, p['code'], year=2025, lock=True)
                assert archive_year(conn, p, observed+timedelta(seconds=2), heads) == 0
            unchanged_dml = len(dml)
            # Exactly 1% = 10,000 facts across the 1m row test set.
            started = time.perf_counter()
            with engine.begin() as conn:
                revised = conn.execute(text('UPDATE yuanhang_daily_price SET amount_yuan=1 '
                    'WHERE unified_code<:upper'),dict(upper='000010.SZ')).rowcount
            revision_seconds = time.perf_counter()-started
            assert revised == 10000
        finally:
            event.remove(engine,'before_cursor_execute',count_dml)
        # One maximal declared financial unit uses the same authoritative writer.
        h = dict(contract=CONTRACT, code='000000.SZ', native_market='USZA',
            actions=[[(date(1990,1,1)+timedelta(days=i//2)).isoformat(),'0','0','0','0',str((i%2+1)/10)]
                     for i in range(2000)],
            capital=[[kind,(date(1990,1,1)+timedelta(days=i)).isoformat(),'100']
                     for kind in ('circulating','free_float','total') for i in range(10000)])
        h['actions'].sort(key=lambda row:(row[0],action_key(row)))
        h['capital'][0][2] = None
        started=time.perf_counter()
        with engine.begin() as conn:
            replace_financial(conn,h,observed,{})
        financial_seconds=time.perf_counter()-started
        action_sql = ('SELECT ex_date,event_key,bonus_ratio,transfer_ratio,rights_ratio,rights_price,cash_per_share '
            'FROM yuanhang_corporate_action WHERE unified_code=:code AND (ex_date>:day OR '
            '(ex_date=:day AND event_key>:key)) ORDER BY ex_date,event_key LIMIT 500')
        action_params = dict(code=h['code'],day='1990-01-01',key='0'*64)
        action_times = []
        with engine.connect() as conn:
            for _ in range(31):
                t=time.perf_counter()
                action_rows=conn.execute(text(action_sql),action_params).all()
                action_times.append((time.perf_counter()-t)*1000)
            assert len(action_rows)==500 and len({(r[0],r[1]) for r in action_rows})==500
            explanations['actions']=[dict(r) for r in conn.execute(text('EXPLAIN '+action_sql),action_params).mappings()]
        queries['actions']=dict(first_query_ms=action_times[0],warm_p95_ms=p95(action_times[1:]),rows=len(action_rows))
        # A whole-market SQL state row is much larger than the fragment returned
        # by the shared per-security accessor. Measure that cost explicitly.
        stamp = observed.isoformat(timespec='microseconds')
        state = dict(contract_version=6,units={f'{i:06d}.SZ': dict(
            price_ranges={str(y): [[f'{y}-01-01',f'{y}-12-31',stamp]] for y in range(1990,2027)},
            full_checked={str(y):stamp for y in range(1990,2027)}, native_market='USZA') for i in range(5578)})
        with engine.begin() as conn:
            conn.execute(text('INSERT INTO collection_state(namespace,project_id,source,dataset,payload,updated_at) '
                'VALUES(:ns,:project,:source,:dataset,:payload,:updated)'),
                dict(ns='capacity',project='ths-yuanhang-prices',source='ths_yuanhang',dataset='yuanhang.price.year',
                     payload=json.dumps(state),updated=observed.replace(tzinfo=None)))
        state_times=[]
        for i in range(30):
            t=time.perf_counter()
            with engine.begin() as conn:
                unit=f'{i:06d}.SZ'
                old,exists=read_unit(conn,'capacity','ths-yuanhang-prices','ths_yuanhang',unit)
                new={**old,'units':{unit:{**old['units'][unit], 'verified_through':'2026-12-31'}}}
                save_unit(conn,'capacity','ths-yuanhang-prices','ths_yuanhang','yuanhang.price.year',unit,new,old,exists)
            state_times.append((time.perf_counter()-t)*1000)
        _,peak=tracemalloc.get_traced_memory()
        tracemalloc.stop()
        with engine.begin() as conn:
            conn.exec_driver_sql('ANALYZE TABLE yuanhang_daily_price')
            allocation = [dict(r) for r in conn.execute(text('SELECT table_name,table_rows,data_length,index_length '
                'FROM information_schema.tables WHERE table_schema=:db'),dict(db=session.database)).mappings()]
        measurements=dict(price_rows=1000000, import_seconds=import_seconds,
            security_query_p95_ms=queries['security']['warm_p95_ms'],
            cross_section_p95_ms=queries['cross_section']['warm_p95_ms'],
            quality_query_p95_ms=queries['quality']['warm_p95_ms'],
            annual_audit_p95_ms=p95(times), annual_archive_ms=archive_ms,
            unchanged_business_dml=unchanged_dml, revision_rows=revised, revision_seconds=revision_seconds,
            financial_seconds=financial_seconds, python_peak_tracked_bytes=peak)
        measurements['actions_query_p95_ms']=queries['actions']['warm_p95_ms']
        measurements.update(price_year_proofs=4000, state_units=5578, state_json_bytes=len(json.dumps(state).encode()),
                            state_unit_write_p95_ms=p95(state_times))
        limits=dict(security_query_p95_ms=200,cross_section_p95_ms=300,annual_audit_p95_ms=1000,
                    quality_query_p95_ms=1000,
                    annual_archive_ms=2000, unchanged_business_dml=0, state_unit_write_p95_ms=2000,
                    actions_query_p95_ms=200)
        report.update(measurements=measurements,limits=limits,queries=queries,explain=explanations,allocation=allocation,
            conditions=dict(data='1m synthetic price facts, 2000 actions, 30000 capital points; independent private MySQL',
                cache='first and warm queries; server buffer pool not flushed, first query is not a cold-disk guarantee',
                memory='tracemalloc Python allocations, not total process or MySQL RSS'),
            reviewed_tradeoffs=['1m price rows are an amplification test, 20m–35m capacity is extrapolation.',
                'Initial bulk import uses the same repository upsert; archive transaction measured separately.',
                'Annual archive revises one fact and its proof inside an existing 250-row year.',
                '1% throughput uses one range update; annual semantic revision/rollback is covered by integration tests.',
                'EXPLAIN reports optimizer row estimates, not exact physical reads; encoded bytes are returned JSON bytes.'])
        schema=(root/'sql/schema.sql').read_text('utf-8')
        manifest=json.loads((root/'sql/schema-contract.json').read_text('utf-8'))
        ownership=json.loads((root/'sql/business-schema.json').read_text('utf-8'))
        report['schema_objects']=objects(schema,manifest,ownership,TABLE_COLUMNS)
        report['ddl_scopes']={k:v['ddl_sha256'] for k,v in report['schema_objects'].items()}
        assert all(measurements[k]<=v for k,v in limits.items())
        session.measurements_complete=True
    print('PASS isolated native history capacity; report='+args.output)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--test-mysql',required=True)
    parser.add_argument('--output',required=True)
    run(parser.parse_args())
