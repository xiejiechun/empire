"""Five-table index capacity through formal writers/reads on a UUID-owned SQL service."""
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
from empire.features.yuanhang_indices import catalog_dataset, member_dataset, price_dataset
from empire.features.yuanhang_indices.audits import member_audit
from empire.features.yuanhang_indices.contract import PROJECTS, SOURCES, digest
from empire.features.yuanhang_indices.price_query import PriceQuery
from empire.features.yuanhang_indices.query import CatalogQuery, MemberQuery
from empire.plugins.infra.collection_state import read_state, save_state
from empire.plugins.infra.collection_state_unit import read_unit, save_unit

TABLES = (*catalog_dataset.TABLES, *member_dataset.TABLES, *price_dataset.TABLES)


def run(args):
    root = project_root()
    paths = [p.relative_to(root).as_posix() for p in (root/'src/empire/features/yuanhang_indices').glob('*.py')]
    paths += ['scripts/measure_yuanhang_indices.py', 'scripts/capacity_session.py',
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
            project, source = PROJECTS[dataset], SOURCES[dataset]
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
        catalog = [dict(code=f'{i:06}', name=f'容量指数{i}', native_market='USZI') for i in range(1000)]
        started = time.perf_counter()
        archive(catalog_dataset, 'catalog', dict(catalog=catalog))
        catalog_seconds = time.perf_counter()-started
        member_payload = dict(code='000000', available=True, members=[[f'{i:06}', '容量证券'] for i in range(1,1001)])
        started = time.perf_counter()
        for i in range(100):
            archive(member_dataset, f'{i:06}', {**member_payload, 'code': f'{i:06}'})
        member_seconds = time.perf_counter()-started
        repeat = archive(member_dataset, '000000', member_payload)
        revision = {**member_payload, 'members': [['000001', '修订名称'], *member_payload['members'][1:]]}
        revised = archive(member_dataset, '000000', revision, observed+timedelta(seconds=1))
        assert repeat['written_count'] == 0 and revised['written_count'] == 2
        values = [[(date(2025,1,1)+timedelta(days=i)).isoformat(), '10','12','9','11',None,'-1'] for i in range(100)]
        price_payload = dict(code='000000', native_market='USZI', start='2025-01-01', through='2025-12-31',
            rows=values, full=True, history_start='2025-01-01')
        started = time.perf_counter()
        for i in range(1000):
            archive(price_dataset, f'{i:06}:2025', {**price_payload,'code':f'{i:06}'})
        price_seconds = time.perf_counter()-started
        repeated_price = archive(price_dataset, '000000:2025', price_payload)
        revised_values = [[values[0][0], '10','12','9','11.5',None,'-1'], *values[1:]]
        revised_price = archive(price_dataset, '000000:2025', {**price_payload,'rows':revised_values}, observed+timedelta(seconds=1))
        assert repeated_price['written_count'] == 0 and revised_price['written_count'] == 2
        async def read(callback):
            return callback()
        queries = (CatalogQuery('capacity'), MemberQuery('capacity'), PriceQuery('capacity'))
        for query in queries:
            query.mysql = SimpleNamespace(read_engine=engine, read=read)
        queries[1].directory = queries[2].directory = queries[0]
        async def measure():
            measurements, details = {}, {}
            for label, callback in (
                ('catalog', lambda: queries[0].browse()), ('members', lambda: queries[1].browse()),
                ('reverse', lambda: queries[1].browse(search='000001')),
                ('member_cursor', lambda: queries[1].browse(after=(awaited_cursor))),
                ('index_range', lambda: queries[2].browse(code='000001')),
                ('cross_date', lambda: queries[2].browse(start='2025-02-01',end='2025-02-15'))):
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
        awaited_cursor = asyncio.run(queries[1].browse(limit=200))['next']
        measurements, details = asyncio.run(measure())
        started = time.perf_counter()
        with engine.connect() as conn:
            audited = member_audit(conn, 'capacity', catalog[:100])
            assert not audited[0] and audited[2] == 100000 and not audited[4]
            for i in range(1000):
                rows = price_dataset.sql_rows(conn, f'{i:06}', 2025)
                assert rows == (revised_values if i == 0 else values)
                checksum = conn.execute(text('SELECT content_hash FROM yuanhang_index_price_year WHERE index_code=:c AND quote_year=2025'),dict(c=f'{i:06}')).scalar_one()
                assert checksum == digest(rows)
        measurements['content_audit_seconds'] = time.perf_counter()-started
        tracemalloc.start()
        member_dataset.normalize(SimpleNamespace(business_key='000000', raw_payload=dict(page=1,code='000000',available=True,
            members=[[f'{i:06}','边界证券'] for i in range(1,10000)])))
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        with engine.connect() as conn:
            conn.exec_driver_sql('ANALYZE TABLE '+','.join(TABLES))
            allocation = [dict(r) for r in conn.execute(text('SELECT TABLE_NAME AS table_name,DATA_LENGTH AS data_length,INDEX_LENGTH AS index_length FROM information_schema.tables WHERE table_schema=:db'),dict(db=session.database)).mappings()]
            plans = {k:[dict(r) for r in conn.exec_driver_sql('EXPLAIN '+sql).mappings()] for k,sql in {
                'source_reverse':"SELECT * FROM ths_index_member WHERE source_code='000001' ORDER BY index_code LIMIT 200",
                'unified_reverse':"SELECT * FROM ths_index_member WHERE unified_code='000001.SZ' ORDER BY index_code LIMIT 200",
                'index_range':"SELECT * FROM yuanhang_index_daily_price WHERE index_code='000001' AND trade_date>='2025-02-01' ORDER BY trade_date LIMIT 200",
                'cross_date':"SELECT * FROM yuanhang_index_daily_price WHERE trade_date BETWEEN '2025-02-01' AND '2025-02-15' ORDER BY trade_date,index_code LIMIT 200"}.items()}
        measurements.update(catalog_import_seconds=catalog_seconds,member_import_seconds=member_seconds,
            price_import_seconds=price_seconds,allocated_bytes=sum(r['data_length']+r['index_length'] for r in allocation),
            unit_python_peak_bytes=peak)
        limits={k:50 for k in measurements if k.endswith('_p95_ms')}
        limits.update(catalog_import_seconds=2,member_import_seconds=20,price_import_seconds=30,
            allocated_bytes=256*1024**2,unit_python_peak_bytes=16*1024**2,content_audit_seconds=30)
        schema_objects=objects((root/'sql/schema.sql').read_text('utf8'),json.loads((root/'sql/schema-contract.json').read_text('utf8')),
            json.loads((root/'sql/business-schema.json').read_text('utf8')),TABLES)
        session.report.update(bindings=session.frozen_inputs,schema_objects=schema_objects,
            ddl_scopes={k:v['ddl_sha256'] for k,v in schema_objects.items()},measurements=measurements,limits=limits,
            queries=details,explain=plans,allocation=allocation,
            conditions=dict(sample='1000 synthetic catalogue identities,100000 member relations,100000 signed/nullable daily facts',
                cache='first query separately; 20 warm repeats; buffer pool not flushed, not a cold-disk claim',
                memory='tracemalloc maximum member unit, not process/MySQL RSS'),
            correctness=dict(repeat_member_dml=repeat['written_count'],revision_member_dml=revised['written_count'],
                repeat_price_dml=repeated_price['written_count'],revision_price_dml=revised_price['written_count'],
                all_content_and_keys_audited=True),
            reviewed_tradeoffs='五表结构化，来源暂无与未知分开；两条成员反查索引及双向日K索引。100000行放大证明所测规模，580×36年空间仍是预算；日K状态按单指数有界读写，详细审计读取正文。')
        if any(measurements[k]>limit for k,limit in limits.items()):
            raise ValueError('指数容量预算未通过，保留测量报告诊断')
        session.measurements_complete=True
    print('PASS five-table index capacity; report='+args.output)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-mysql',required=True)
    parser.add_argument('--output',required=True)
    run(parser.parse_args())
