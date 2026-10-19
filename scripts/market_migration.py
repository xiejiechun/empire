"""Market-only adapter for the shared explicit maintenance journal/locking model."""
import hashlib
import json
import re
import shutil
from pathlib import Path

from sqlalchemy import inspect, text

from empire.features.kaipanla.codec import encode
from empire.features.kaipanla.normalization import digest, validate
from empire.features.kaipanla.repository import head_record, read_day, write_day
from empire.features.kaipanla.storage_contract import MARKET_TABLES
from scripts.business_migration_engine import identity, save

ROOT = Path(__file__).resolve().parents[1]
PREFIX, BACKUP = 'empire_market_v2_', 'empire_market_v1_'


def definitions():
    body = (ROOT / 'sql/schema.sql').read_text('utf-8')
    return {m[1]: m[0] for m in re.finditer(r'CREATE TABLE IF NOT EXISTS (\w+) \(.*?ENGINE=.*?;', body, re.S)
            if m[1] in MARKET_TABLES}


def implementation_hash():
    paths = ['sql/schema.sql', 'sql/schema-contract.json', 'scripts/market_migration.py',
             'src/empire/features/kaipanla/storage_contract.py', 'src/empire/features/kaipanla/codec.py',
             'src/empire/features/kaipanla/repository.py', 'src/empire/features/kaipanla/trade_blocks.py',
             'src/empire/features/kaipanla/dataset.py',
             'src/empire/features/kaipanla/product_source.py',
             'src/empire/features/kaipanla/contract.py', 'docs/kaipanla-field-dictionary.md']
    return hashlib.sha256(b''.join((ROOT/p).read_bytes() for p in paths)).hexdigest()


def structures(engine, prefix='', tables=MARKET_TABLES):
    with engine.connect() as conn:
        return {t: conn.exec_driver_sql(f'SHOW CREATE TABLE `{prefix+t}`').one()[1].replace(
            '`'+prefix+t+'`', '`'+t+'`', 1) for t in tables}


def units(conn, *, prefix='', old=False):
    cursor = None
    while True:
        sql = f'SELECT * FROM {prefix}stock_market_day'
        args = {}
        if cursor:
            sql += ' WHERE (kind,unified_code,trade_date)>(:kind,:security,:day)'
            args = dict(kind=cursor[0], security=cursor[1], day=cursor[2])
        rows = conn.execute(text(sql+' ORDER BY kind,unified_code,trade_date LIMIT 32'), args).mappings().all()
        if not rows:
            return
        for stored in rows:
            row = json.loads(stored['payload']) if old else read_day(conn, stored, prefix=prefix)
            validate(row, stored['kind'])
            if (digest(row) != stored['content_hash'] or row['code']+'.'+row['market'] != stored['unified_code']
                    or row['trade_date'] != stored['trade_date'].isoformat()):
                raise ValueError(f'迁移内容或身份不匹配：{stored["kind"]}/{stored["unified_code"]}/{stored["trade_date"]}')
            yield stored, row
        last = rows[-1]
        cursor = last['kind'], last['unified_code'], last['trade_date']


def inventory(engine, *, prefix='', old=False):
    hash_value, count, kinds, facts = hashlib.sha256(), 0, {}, {t: 0 for t in MARKET_TABLES[1:]}
    with engine.connect() as conn:
        conn.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
        for stored, row in units(conn, prefix=prefix, old=old):
            wire = json.dumps([row, stored['version_observed_at'].isoformat()], ensure_ascii=False,
                              sort_keys=True, separators=(',', ':')).encode()
            hash_value.update(len(wire).to_bytes(8, 'big')+wire)
            count += 1
            kinds[row['kind']] = kinds.get(row['kind'], 0)+1
            _, mapped = encode(row, stored['content_hash'], stored['version_observed_at'])
            for table, records in mapped.items():
                facts[table] += len(records)
        if not old:
            for table, expected in facts.items():
                actual = conn.exec_driver_sql(f'SELECT COUNT(*) FROM `{prefix+table}`').scalar_one()
                if actual != expected:
                    raise ValueError(f'{table} 存在缺失或孤立明细：{actual}/{expected}')
    return dict(units=count, kinds=kinds, sha256=hash_value.hexdigest(), facts=facts)


def untouched(engine):
    from empire.plugins.infra.schema_manifest import manifest
    results = {}
    with engine.connect().execution_options(stream_results=True) as conn:
        conn.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
        for table, shape in manifest()['tables'].items():
            if table in MARKET_TABLES:
                continue
            h, count = hashlib.sha256(), 0
            order = ','.join('`'+k+'`' for k in shape['primary'])
            rows = conn.exec_driver_sql(f'SELECT * FROM `{table}` ORDER BY {order}')
            for row in rows:
                wire = json.dumps(tuple(row), default=str, ensure_ascii=False, separators=(',', ':')).encode()
                h.update(len(wire).to_bytes(8, 'big')+wire)
                count += 1
            rows.close()
            results[table] = dict(rows=count, sha256=h.hexdigest())
    return results


def preflight(engine):
    with engine.connect() as conn:
        allocated = conn.execute(text('SELECT DATA_LENGTH+INDEX_LENGTH FROM information_schema.tables '
            "WHERE table_schema=DATABASE() AND table_name='stock_market_day'")).scalar_one()
        directory = conn.exec_driver_sql('SELECT @@datadir').scalar_one()
        free = shutil.disk_usage(directory).free
    # Typed minute indexes may expand several times; do not infer head-only cost.
    required = max(int(allocated or 0)*8, 2*1024**3)
    if free < required:
        raise ValueError(f'迁移空间不足：至少{required}字节，可用{free}')
    return dict(target=identity(engine), before=inventory(engine, old=True),
                untouched=untouched(engine), free=free, required=required, read_only=True)


def verify(engine, journal):
    state = json.loads(Path(journal).read_text('utf-8'))
    if state['target'] != identity(engine) or state['implementation'] != implementation_hash():
        raise ValueError('维护日志库身份或实现摘要不匹配')
    if structures(engine) != state['new_structure']:
        raise ValueError('迁移目标结构已变化')
    actual = inventory(engine)
    if actual != state['before'] or untouched(engine) != state['untouched']:
        raise ValueError('业务内容或未涉及表已改变，不能沿用迁移基线/回退')
    return dict(passed=True, after=actual)


def maintain(engine, journal, command='migrate', fail_after=None):
    path = Path(journal).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with engine.connect() as guard:
        if guard.exec_driver_sql("SELECT GET_LOCK('empire-business-schema-v2',0)").scalar_one() != 1:
            raise RuntimeError('同数据库维护正在进行')
        try:
            if command == 'verify':
                return verify(engine, path)
            with engine.connect() as conn:
                tables = set(inspect(conn).get_table_names())
            if command == 'status':
                return json.loads(path.read_text('utf-8')) if path.exists() else {'phase': 'not_started'}
            if path.exists():
                state = json.loads(path.read_text('utf-8'))
                if state['target'] != identity(engine) or state['implementation'] != implementation_hash():
                    raise ValueError('维护日志库身份或实现摘要不匹配')
            else:
                if any(t.startswith((PREFIX, BACKUP)) for t in tables):
                    raise ValueError('维护表存在但缺少对应日志，拒绝覆盖')
                state = {**preflight(engine), 'implementation': implementation_hash(), 'phase': 'copy',
                         'old_structure': structures(engine, tables=('stock_market_day',)), 'cursor': None}
                save(path, state)
            if command == 'rollback':
                verify(engine, path)
                if structures(engine, BACKUP, ('stock_market_day',)) != state['old_structure']:
                    raise ValueError('旧恢复副本结构变化')
                if inventory(engine, prefix=BACKUP, old=True) != state['before']:
                    raise ValueError('旧恢复副本不匹配')
                with engine.begin() as conn:
                    pairs = [f'`{t}` TO `{PREFIX+t}`' for t in MARKET_TABLES]
                    pairs.append(f'`{BACKUP}stock_market_day` TO `stock_market_day`')
                    conn.exec_driver_sql('RENAME TABLE '+','.join(pairs))
                state['phase'] = 'rolled_back'
                save(path, state)
                return state
            if BACKUP+'stock_market_day' in tables:
                result = verify(engine, path)
                state.update(phase='verified', after=result['after'])
                save(path, state)
                return state
            if state['phase'] == 'rolled_back':
                raise ValueError('日志已回退，须另行制定维护方案')
            if (structures(engine, tables=('stock_market_day',)) != state['old_structure']
                    or inventory(engine, old=True) != state['before'] or untouched(engine) != state['untouched']):
                raise ValueError('停机期间结构或内容改变')
            with engine.begin() as conn:
                for table, ddl in definitions().items():
                    conn.exec_driver_sql(ddl.replace('IF NOT EXISTS '+table, 'IF NOT EXISTS '+PREFIX+table))
            actual_structures = structures(engine, PREFIX)
            if state.get('new_structure') and state['new_structure'] != actual_structures:
                raise ValueError('影子结构改变，拒绝续跑')
            state['new_structure'] = actual_structures
            save(path, state)
            with engine.connect() as reader:
                for stored, row in units(reader, old=True):
                    key = [stored['kind'], stored['unified_code'], str(stored['trade_date'])]
                    if state['cursor'] and key <= state['cursor']:
                        continue
                    writer = reader
                    try:
                        existing = head_record(writer, stored['kind'], stored['unified_code'], stored['trade_date'], prefix=PREFIX)
                        if not existing:
                            write_day(writer, row, stored['content_hash'], stored['version_observed_at'], prefix=PREFIX, compare=False)
                        actual = head_record(writer, stored['kind'], stored['unified_code'], stored['trade_date'], prefix=PREFIX)
                        if read_day(writer, actual, prefix=PREFIX) != row or actual['version_observed_at'] != stored['version_observed_at']:
                            raise ValueError('影子逐单元读回不一致')
                        writer.commit()
                    except BaseException:
                        writer.rollback()
                        raise
                    state['cursor'] = key
                    save(path, state)
                    if fail_after == key:
                        raise RuntimeError('injected interruption')
            if inventory(engine, prefix=PREFIX) != state['before']:
                raise ValueError('影子完整集合不一致，禁止切换')
            if inventory(engine, old=True) != state['before'] or untouched(engine) != state['untouched']:
                raise ValueError('切换前旧业务或其他表变化，禁止切换')
            state['phase'] = 'ready_to_switch'
            save(path, state)
            with engine.begin() as conn:
                pairs = ['`stock_market_day` TO `'+BACKUP+'stock_market_day`']
                pairs += [f'`{PREFIX+t}` TO `{t}`' for t in MARKET_TABLES]
                conn.exec_driver_sql('RENAME TABLE '+','.join(pairs))
            state['phase'] = 'switched'
            save(path, state)
            result = verify(engine, path)
            state.update(phase='verified', after=result['after'])
            save(path, state)
            return state
        finally:
            guard.exec_driver_sql("SELECT RELEASE_LOCK('empire-business-schema-v2')")
