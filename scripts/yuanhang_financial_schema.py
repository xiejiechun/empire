"""Bounded explicit v3 financial-shape revision; never invoked at startup."""
from copy import deepcopy

from sqlalchemy import text

from empire.plugins.infra.schema_manifest import manifest, shape, validate_shapes
from empire.sources.yuanhang_payload import ACTION_FIELDS, action_key, digest, number
from scripts.create_name_change_schema import ddl

OLD_ACTION_CHECK = ('((bonus_ratio>=0)and(transfer_ratio>=0)and(rights_ratio>=0)'
    'and(rights_price>=0)and(cash_per_share>=0)and((rights_ratio=0)or(rights_price>0)))')


def _action_facts(conn, *, fill=False):
    """Map each old row one-to-one, hashing content independently of its new key."""
    parts, total, after_code, after_day = [], 0, '', '1900-01-01'
    while True:
        rows = conn.execute(text('SELECT unified_code,ex_date,event_key,' + ','.join(ACTION_FIELDS)
            + ' FROM yuanhang_corporate_action WHERE unified_code>:code OR '
            '(unified_code=:code AND ex_date>:day) ORDER BY unified_code,ex_date LIMIT 500'),
            dict(code=after_code, day=after_day)).all()
        if not rows:
            break
        updates, batch = [], []
        for code, when, key, *values in rows:
            event = [when.isoformat()] + [number(v, signed=k == 'bonus_ratio')
                for k, v in zip(ACTION_FIELDS, values, strict=True)]
            expected = action_key(event)
            if key is None and fill:
                updates.append(dict(code=code, day=when, key=expected))
            elif key != expected:
                raise RuntimeError('旧权息事件身份与内容不一致，拒绝迁移')
            batch.append([code, *event])
        if updates:
            conn.execute(text('UPDATE yuanhang_corporate_action SET event_key=:key '
                'WHERE unified_code=:code AND ex_date=:day AND event_key IS NULL'), updates)
        parts.append(digest(batch))
        total += len(rows)
        after_code, after_day = rows[-1][0], rows[-1][1]
    return dict(rows=total, content_hash=digest(parts))


def _check(table, name):
    return ddl(table).split('CONSTRAINT ' + name + ' ', 1)[1].rsplit(')', 1)[0].strip()


def _capital_facts(conn):
    parts, total, after = [], 0, ('', '', '1900-01-01')
    while True:
        rows = conn.execute(text('SELECT unified_code,capital_kind,effective_date,shares '
            'FROM yuanhang_capital WHERE (unified_code,capital_kind,effective_date)>(:code,:kind,:day) '
            'ORDER BY unified_code,capital_kind,effective_date LIMIT 500'),
            dict(zip(('code', 'kind', 'day'), after, strict=True))).all()
        if not rows:
            break
        parts.append(digest([[r[0], r[1], r[2].isoformat(), number(r[3], nullable=r[1] == 'circulating')]
                             for r in rows]))
        total += len(rows)
        after = tuple(rows[-1][:3])
    return dict(rows=total, content_hash=digest(parts))


def financial_revision(conn):
    tables = ('yuanhang_corporate_action', 'yuanhang_capital')
    expected = manifest()['tables']
    actual = {t: shape(conn, t) for t in tables}
    old_action = deepcopy(expected[tables[0]])
    del old_action['columns']['event_key']
    old_action['primary'] = ['unified_code', 'ex_date']
    old_action['checks']['ck_yuanhang_action_values'] = OLD_ACTION_CHECK
    intermediate = deepcopy(old_action)
    intermediate['columns']['event_key'] = {**expected[tables[0]]['columns']['event_key'], 'nullable': True}
    old_capital = deepcopy(expected[tables[1]])
    old_capital['columns']['shares']['nullable'] = False
    old_capital['checks']['ck_yuanhang_capital_shares'] = '(shares>0)'
    if actual[tables[0]] not in (old_action, intermediate, expected[tables[0]]):
        raise RuntimeError('原权息表不是已知结构，拒绝修改')
    if actual[tables[1]] not in (old_capital, expected[tables[1]]):
        raise RuntimeError('原股本表不是已知结构，拒绝修改')
    changed, evidence = [], {}
    if actual[tables[0]] != expected[tables[0]]:
        if actual[tables[0]] == old_action:
            conn.exec_driver_sql('ALTER TABLE yuanhang_corporate_action ADD event_key '
                'CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL AFTER ex_date')
            conn.commit()
        before = _action_facts(conn, fill=True)
        conn.commit()
        if _action_facts(conn) != before:
            raise RuntimeError('旧权息正文在身份回填时发生变化')
        conn.exec_driver_sql('ALTER TABLE yuanhang_corporate_action DROP PRIMARY KEY, '
            'MODIFY event_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, '
            'ADD PRIMARY KEY(unified_code,ex_date,event_key), DROP CHECK ck_yuanhang_action_values, '
            'ADD CONSTRAINT ck_yuanhang_action_values ' + _check(tables[0], 'ck_yuanhang_action_values'))
        conn.commit()
        if _action_facts(conn) != before:
            raise RuntimeError('旧权息正文在主键迁移后发生变化')
        changed.append(tables[0])
        evidence['actions'] = before
    if actual[tables[1]] != expected[tables[1]]:
        before = _capital_facts(conn)
        conn.exec_driver_sql('ALTER TABLE yuanhang_capital MODIFY shares DECIMAL(28,10) NULL, '
            'DROP CHECK ck_yuanhang_capital_shares, ADD CONSTRAINT ck_yuanhang_capital_shares '
            + _check(tables[1], 'ck_yuanhang_capital_shares'))
        conn.commit()
        if _capital_facts(conn) != before:
            raise RuntimeError('旧股本正文在空值约束迁移后发生变化')
        changed.append(tables[1])
        evidence['capital'] = before
    validate_shapes(conn, tables)
    return dict(changed=changed, evidence=evidence)
