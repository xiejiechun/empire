"""Three-table ETF capacity through formal writers/reads on a UUID-owned SQL service."""
import argparse
import asyncio
import json
import time
import tracemalloc
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from capacity_session import CapacitySession
from create_name_change_schema import ddl
from schema_evidence_scope import objects
from sqlalchemy import text

from empire.contracts.data import make_envelope
from empire.core.config import load_config, project_root
from empire.features.yuanhang_etf import catalog_dataset, price_dataset
from empire.features.yuanhang_etf.contract import PROJECTS, digest
from empire.features.yuanhang_etf.latest import LatestQuery
from empire.features.yuanhang_etf.price_query import PriceQuery
from empire.features.yuanhang_etf.query import CatalogQuery
from empire.plugins.infra.collection_state import read_state, save_state
from empire.plugins.infra.collection_state_unit import read_unit, save_unit
from empire.plugins.infra.redis_store import create_client

TABLES = (*catalog_dataset.TABLES, *price_dataset.TABLES)


async def measure_latest(session, catalog):
    cfg = load_config()['redis']
    redis = create_client(cfg)
    store = LatestQuery()
    store.redis, store.key = redis, 'empire:test:'+session.run_id+':yuanhang:etf:latest'
    rows = [dict(r, quote_at=None, net_value_date=None, previous_close='100', open='100', high='101',
        low='99', latest='100.045', volume='1000000', amount='100045000', net_value='100') for r in catalog]
    snapshot = dict(schema=1, catalog_hash=digest(catalog), observed_at=datetime.now(UTC).isoformat(), rows=rows)
    try:
        assert await store.save(snapshot)
        assert not await store.save(snapshot)
        samples, sizes = [], []
        for _ in range(21):
            before = time.perf_counter()
            result = await store.browse(order=dict(field='latest', direction='desc'))
            samples.append((time.perf_counter()-before)*1000)
            assert len(result['rows']) == 200 and result['total'] == 5000
            sizes.append(len(json.dumps(result,ensure_ascii=False).encode()))
        tracemalloc.start()
        await store.save({**snapshot, 'observed_at': datetime.now(UTC).isoformat()})
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return dict(latest_p95_ms=sorted(samples[1:])[18], latest_python_peak_bytes=peak), dict(
            first_ms=samples[0], warm_ms=samples[1:], encoded_bytes=sizes,
            redis_bytes=await redis.memory_usage(store.key), ttl=await redis.ttl(store.key),
            old_version_rejected=True, rows=5000, source_time_unknown=True)
    finally:
        await redis.delete(store.key)
        await redis.aclose()


def run(args):
    root = project_root()
    paths = [p.relative_to(root).as_posix() for p in (root/'src/empire/features/yuanhang_etf').glob('*.py')]
    paths += ['scripts/measure_yuanhang_etf.py', 'scripts/capacity_session.py',
        'src/empire/plugins/infra/collection_state_unit.py', 'src/empire/sources/yuanhang_ranges.py']
    settings = json.loads(Path(args.test_mysql).read_text('utf8'))
    session = CapacitySession(load_config()['mysql'], settings, root=root, subject='indices',
        output=args.output, input_paths=paths)
    with session:
        engine = session.engine
        with engine.begin() as conn:
            for table in (*TABLES, 'collection_state'):
                conn.exec_driver_sql(ddl(table))
        observed = datetime.now(UTC)
        def archive(mapping, key, payload, stamp=observed):
            dataset = next(iter(mapping.DATASETS))
            project, source = PROJECTS[dataset], 'ths_yuanhang'
            envelope = make_envelope(source=source, dataset=dataset, business_key=key, job_key=project+'-v1',
                batch_id='capacity', run_id='capacity', payload=dict(page=1, **payload)).model_copy(update={'observed_at': stamp})
            data = mapping.normalize(envelope)
            unit = mapping.state_unit(data) if hasattr(mapping, 'state_unit') else None
            with engine.begin() as conn:
                previous, exists = read_unit(conn, 'capacity', project, source, unit) if unit else (read_state(conn, 'capacity', project, source), True)
                outcome = mapping.write(conn, envelope, {**data, 'archive_state': previous})
                updated = mapping.archive_state(envelope, data, outcome, previous)
                if unit:
                    save_unit(conn, 'capacity', project, source, mapping.FINGERPRINT_NAMESPACE, unit, updated, previous, exists)
                else:
                    save_state(conn, 'capacity', project, source, mapping.FINGERPRINT_NAMESPACE, updated, previous)
            return outcome
        catalog = [dict(code=f'{i:06}.SH', name=f'容量ETF{i}', native_market='USHJ') for i in range(5000)]
        started = time.perf_counter()
        archive(catalog_dataset, 'catalog', dict(catalog=catalog))
        catalog_seconds = time.perf_counter()-started
        first=date(2025,1,1)
        values=[[(first+timedelta(days=i)).isoformat(),'10','12','9','11',None,'-1'] for i in range(250)]
        started=time.perf_counter()
        for i in range(400):
            code=f'{i:06}.SH'
            price_payload=dict(code=code,native_market='USHJ',start='2025-01-01',through='2025-12-31',rows=values,full=True,history_start=values[0][0])
            archive(price_dataset, code+':2025', price_payload)
        price_seconds=time.perf_counter()-started
        price_payload={**price_payload,'code':'000000.SH'}
        repeated_price=archive(price_dataset,'000000.SH:2025',price_payload)
        revised_values=[[values[0][0],'10','12','9','11.5',None,'-1'],*values[1:]]
        revised_price=archive(price_dataset,'000000.SH:2025',{**price_payload,'rows':revised_values},observed+timedelta(seconds=1))
        assert repeated_price['written_count']==0 and revised_price['written_count']==2
        async def read(callback):
            return callback()
        queries = (CatalogQuery('capacity'), PriceQuery('capacity'))
        for query in queries:
            query.mysql = SimpleNamespace(read_engine=engine, read=read)
        queries[1].directory = queries[0]
        async def measure():
            measurements, details = {}, {}
            for label, callback in (
                ('catalog', lambda: queries[0].browse()),
                ('etf_range', lambda: queries[1].browse(code='000001.SH')),
                ('cross_date', lambda: queries[1].browse(start='2025-02-01',end='2025-02-15'))):
                samples, counts, sizes = [], [], []
                for _ in range(21):
                    before = time.perf_counter()
                    result = await callback()
                    samples.append((time.perf_counter()-before)*1000)
                    assert result['rows']
                    counts.append(len(result['rows']))
                    sizes.append(len(json.dumps(result,default=str,ensure_ascii=False).encode()))
                measurements[label+'_p95_ms'] = sorted(samples[1:])[18]
                details[label] = dict(first_ms=samples[0],warm_ms=samples[1:],returned_rows=counts,encoded_bytes=sizes)
            return measurements, details
        measurements, details = asyncio.run(measure())
        latest_measurements, details['latest'] = asyncio.run(measure_latest(session, catalog))
        measurements.update(latest_measurements)
        started = time.perf_counter()
        with engine.connect() as conn:
            for i in range(400):
                code=f'{i:06}.SH'
                rows=price_dataset.sql_rows(conn,code,2025)
                assert rows==(revised_values if i==0 else values)
                checksum=conn.execute(text('SELECT content_hash FROM yuanhang_etf_price_year WHERE unified_code=:c AND quote_year=2025'),dict(c=code)).scalar_one()
                assert checksum==digest(rows)
        measurements['content_audit_seconds'] = time.perf_counter()-started
        tracemalloc.start()
        catalog_dataset.normalize(SimpleNamespace(business_key='catalog',raw_payload=dict(page=1,catalog=catalog)))
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        with engine.connect() as conn:
            conn.exec_driver_sql('ANALYZE TABLE '+','.join(TABLES))
            allocation = [dict(r) for r in conn.execute(text('SELECT TABLE_NAME AS table_name,DATA_LENGTH AS data_length,INDEX_LENGTH AS index_length FROM information_schema.tables WHERE table_schema=:db'),dict(db=session.database)).mappings()]
            plans = {k:[dict(r) for r in conn.exec_driver_sql('EXPLAIN '+sql).mappings()] for k,sql in {
                'etf_range':"SELECT * FROM yuanhang_etf_daily_price WHERE unified_code='000001.SH' AND trade_date>='2025-02-01' ORDER BY trade_date LIMIT 200",
                'cross_date':"SELECT * FROM yuanhang_etf_daily_price WHERE trade_date BETWEEN '2025-02-01' AND '2025-02-15' ORDER BY trade_date,unified_code LIMIT 200"}.items()}
        measurements.update(catalog_import_seconds=catalog_seconds,
            price_import_seconds=price_seconds,allocated_bytes=sum(r['data_length']+r['index_length'] for r in allocation),
            unit_python_peak_bytes=peak)
        limits={k:100 for k in measurements if k.endswith('_p95_ms')}
        limits.update(catalog_import_seconds=2,price_import_seconds=30,
            allocated_bytes=256*1024**2,unit_python_peak_bytes=16*1024**2,content_audit_seconds=30,
            latest_python_peak_bytes=64*1024**2)
        schema_objects=objects((root/'sql/schema.sql').read_text('utf8'),json.loads((root/'sql/schema-contract.json').read_text('utf8')),
            json.loads((root/'sql/business-schema.json').read_text('utf8')),TABLES)
        session.report.update(bindings=session.frozen_inputs,schema_objects=schema_objects,
            ddl_scopes={k:v['ddl_sha256'] for k,v in schema_objects.items()},measurements=measurements,limits=limits,
            queries=details,explain=plans,allocation=allocation,
            conditions=dict(sample='5000 synthetic ETF identities,400 ETFs ×250 dates =100000 nullable/signed daily facts',
                cache='first query separately; 20 warm repeats; buffer pool not flushed, not a cold-disk claim',
                memory='tracemalloc maximum catalog unit, not process/MySQL RSS'),
            correctness=dict(repeat_price_dml=repeated_price['written_count'],revision_price_dml=revised_price['written_count'],
                all_content_and_keys_audited=True),
            reviewed_tradeoffs='三表结构化与双向日K索引；ETF按完整统一代码独立于股票名单。100000行放大只证明所测规模，当前1741只及实际跨度空间另作估算；不声称5000×150年可放入16GiB。')
        if any(measurements[k]>limit for k,limit in limits.items()):
            raise ValueError('指数容量预算未通过，保留测量报告诊断')
        session.measurements_complete=True
    print('PASS three-table ETF capacity; report='+args.output)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-mysql',required=True)
    parser.add_argument('--output',required=True)
    run(parser.parse_args())
