"""Resumable shadow copy and atomic multi-table rename; application must be stopped."""
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import inspect, text

from scripts.business_migration_inventory import (
    BACKUP,
    NEW,
    OLD,
    PREFIX,
    definitions,
    inventory,
    quote,
    selection,
    target_columns,
    validate_old,
)


def save(path, state):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def identity(engine):
    with engine.connect() as conn:
        return dict(zip(('server_uuid', 'port', 'database'), conn.exec_driver_sql(
            'SELECT @@server_uuid,@@port,DATABASE()').one(), strict=True))


def structure_hash():
    return hashlib.sha256(json.dumps(definitions(), sort_keys=True).encode()).hexdigest()


def structures(engine, prefix='', tables=NEW):
    """Bind all columns, indexes and constraints; table rename alone is immaterial."""
    with engine.connect() as conn:
        return {table: conn.exec_driver_sql('SHOW CREATE TABLE '+quote(prefix+table)).one()[1].replace(
            '`'+prefix+table+'`', '`'+table+'`', 1) for table in tables}


def require_space(engine):
    with engine.connect() as conn:
        datadir = conn.exec_driver_sql('SELECT @@datadir').scalar_one()
        needed = conn.execute(text('SELECT SUM(DATA_LENGTH+INDEX_LENGTH) FROM information_schema.TABLES '
            'WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN (' + ','.join(':t'+str(i) for i in range(len(OLD))) + ')'),
            {'t'+str(i): t for i,t in enumerate(OLD)}).scalar_one() or 0
    free = shutil.disk_usage(datadir).free
    reserve = int(needed) * 2 + 1024**3
    if free < reserve:
        raise RuntimeError(f'迁移磁盘余量不足：需要至少 {reserve} 字节，可用 {free}')
    return dict(allocated_before=int(needed), free=free, required=reserve)


def migrate(engine, journal, *, fail_after=None):
    journal = Path(journal).resolve()
    journal.parent.mkdir(parents=True, exist_ok=True)
    current = identity(engine)
    with engine.connect() as guard:
        if guard.execute(text("SELECT GET_LOCK('empire-business-schema-v2',0)")).scalar_one() != 1:
            raise RuntimeError('同数据库维护正在进行')
        try:
            with engine.connect() as conn:
                tables = set(inspect(conn).get_table_names())
            if journal.exists():
                state = json.loads(journal.read_text(encoding='utf-8'))
                if state['target'] != current or state['schema_sha256'] != structure_hash():
                    raise ValueError('维护日志目标或实现结构不匹配')
            else:
                if any(t.startswith((PREFIX, BACKUP)) for t in tables):
                    raise ValueError('已有维护副本但缺少对应日志，拒绝覆盖')
                validate_old(engine)
                state = dict(target=current, schema_sha256=structure_hash(), phase='inventory', copied=[],
                             started_at=datetime.now(UTC).isoformat(), space=require_space(engine),
                             old_structure=structures(engine, tables=OLD))
                save(journal, state)
            if all(BACKUP+t in tables for t in OLD):
                if any(PREFIX+t in tables for t in NEW):
                    raise ValueError('切换状态矛盾')
                if structures(engine) != state.get('new_structure'):
                    raise ValueError('切换后实际结构变化')
                actual = inventory(engine)
                if actual != state['before']:
                    raise ValueError('切换后内容变化或不匹配，拒绝重新迁移/回退')
                state.update(phase='verified', after=actual)
                save(journal, state)
                return state
            if state['phase'] == 'rolled_back':
                raise ValueError('本维护日志已经回退；保留证据并使用新维护方案')
            validate_old(engine)
            if structures(engine, tables=OLD) != state['old_structure']:
                raise ValueError('旧表结构变化，拒绝继续')
            before = inventory(engine, old=True)
            if 'before' in state and before != state['before']:
                raise ValueError('停写期间旧数据发生变化，不能续用旧迁移证明')
            state.update(before=before, phase='copy')
            save(journal, state)
            for table in NEW:
                if table in state['copied']:
                    continue
                # Only this journal's allowlisted disposable target may be recreated.
                shadow = PREFIX+table
                with engine.begin() as conn:
                    conn.execute(text('DROP TABLE IF EXISTS ' + quote(shadow)))
                    ddl = definitions()[table].replace('IF NOT EXISTS '+table, 'IF NOT EXISTS '+shadow)
                    conn.execute(text(ddl))
                    conn.execute(text('INSERT INTO ' + quote(shadow) + ' (' +
                        ','.join('`'+c+'`' for c in target_columns(table)) + ') ' + selection(table, old=True)))
                state['copied'].append(table)
                save(journal, state)
                if fail_after == table:
                    raise RuntimeError('injected interruption after '+table)
            after = inventory(engine, PREFIX)
            if after != before:
                raise ValueError('影子表业务键/内容/版本/关联集合不一致，禁止切换')
            state.update(phase='ready_to_switch', after=after, new_structure=structures(engine, PREFIX))
            save(journal, state)
            pairs = [quote(t)+' TO '+quote(BACKUP+t) for t in OLD]
            pairs += [quote(PREFIX+t)+' TO '+quote(t) for t in NEW]
            with engine.begin() as conn:
                conn.execute(text('RENAME TABLE '+','.join(pairs)))
            state['phase'] = 'switched'
            save(journal,state)
            actual = inventory(engine)
            if actual != before:
                raise ValueError('切换后核验不一致，保持停机')
            state.update(phase='verified', after=actual)
            save(journal,state)
            return state
        finally:
            guard.execute(text("SELECT RELEASE_LOCK('empire-business-schema-v2')"))


def verify(engine, journal):
    state = json.loads(Path(journal).read_text(encoding='utf-8'))
    if state['target'] != identity(engine) or state['schema_sha256'] != structure_hash():
        raise ValueError('维护目标或结构不匹配')
    if structures(engine) != state.get('new_structure'):
        raise ValueError('正式表实际结构变化')
    actual = inventory(engine)
    if actual != state['before']:
        raise ValueError('业务集合与迁移基线不一致（恢复运行后变化须另行核验）')
    return dict(passed=True, inventory=actual)


def _rollback(engine, journal):
    verify(engine,journal)  # No writes since switch: never discard newly archived business.
    state = json.loads(Path(journal).read_text(encoding='utf-8'))
    if structures(engine, BACKUP, OLD) != state['old_structure']:
        raise ValueError('旧表恢复结构不匹配')
    if inventory(engine,BACKUP,old=True) != state['before']:
        raise ValueError('旧表恢复副本不匹配')
    pairs = [quote(t)+' TO '+quote(PREFIX+t) for t in NEW]
    pairs += [quote(BACKUP+t)+' TO '+quote(t) for t in OLD]
    with engine.begin() as conn:
        conn.execute(text('RENAME TABLE '+','.join(pairs)))
    state['phase']='rolled_back'
    save(Path(journal),state)
    return state


def rollback(engine, journal):
    with engine.connect() as guard:
        if guard.execute(text("SELECT GET_LOCK('empire-business-schema-v2',0)")).scalar_one() != 1:
            raise RuntimeError('同数据库维护正在进行')
        try:
            return _rollback(engine, journal)
        finally:
            guard.execute(text("SELECT RELEASE_LOCK('empire-business-schema-v2')"))
