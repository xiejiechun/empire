"""Explicit contract4 upgrade; preserve facts, source ranks and observation versions."""
import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import inspect, text

try:
    from .create_name_change_schema import ddl
except ImportError:
    from create_name_change_schema import ddl
from empire.__main__ import acquire_instance_lock
from empire.contracts.holders import MEMBER_FIELDS, REPORT_FIELDS, digest, report_key, validate
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.plugins.datasets.holders import HolderDataset, decode
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.schema_manifest import validate_shapes
from empire.plugins.pipeline.fingerprints import FingerprintCache


def facts(row):
    """Representation-independent facts, including the original bond rank."""
    members = []
    for member in row['members']:
        m = {k: v for k, v in member.items() if k not in ('seq', 'source_rank')}
        m['source_position'] = member['source_rank'] if row['kind'] == 'bond_holders' else member['seq']
        members.append(m)
    return {**{k:v for k,v in row.items() if k != 'quality_flags'}, 'members': sorted(members, key=digest)}


def batches(conn):
    last = ''
    while True:
        heads = conn.execute(text('SELECT * FROM holder_report WHERE report_key>:last ORDER BY report_key LIMIT 100'), {'last': last}).mappings().all()
        if not heads:
            return
        params = {'k'+str(i): r['report_key'] for i, r in enumerate(heads)}
        body = conn.execute(text('SELECT * FROM holder_member WHERE report_key IN (' + ','.join(':'+k for k in params) + ') ORDER BY report_key,member_group,seq LIMIT 40001'), params).mappings().all()
        if len(body) > 40000:
            raise ValueError('维护批量明细超出有界预算')
        grouped = {key: [] for key in params.values()}
        for m in body:
            grouped[m['report_key']].append(m)
        yield [(head, grouped[head['report_key']]) for head in heads]
        last = heads[-1]['report_key']


def normalized(head, body):
    row = {**decode({**head, 'quality_flags': head.get('quality_flags', 0)}, REPORT_FIELDS), 'members': []}
    positions = {'current': 0, 'exited': 0}
    for member in body:
        rank = member.get('source_rank')
        if row['kind'] == 'bond_holders' and rank is None:
            rank = member['seq']
        m = decode({**member, 'source_rank': rank}, MEMBER_FIELDS)
        positions[m['member_group']] += 1
        m['seq'] = positions[m['member_group']]
        row['members'].append(m)
    return row


def inventory(conn, *, verify=False):
    result = dict(reports=0, members=0, facts=digest([]), versions=digest([]))
    for batch in batches(conn):
        for head, body in batch:
            row = normalized(head, body)
            if head['member_count'] != sum(m['member_group'] == 'current' for m in body) or head['exit_count'] != sum(m['member_group'] == 'exited' for m in body) or head['report_key'] != report_key(row):
                raise ValueError('维护前后报告身份或人数证明损坏')
            if verify:
                validate(row['kind'], row['unified_code'], [row])
                if head['content_hash'] != digest(row) or any(m['seq'] != n['seq'] for m,n in zip(body,row['members'])):
                    raise ValueError('持有人升级摘要或规范位置未完成')
            result['reports'] += 1
            result['members'] += len(body)
            result['facts'] = digest([result['facts'], head['report_key'], facts(row)])
            result['versions'] = digest([result['versions'], head['report_key'], str(head['version_observed_at'])])
    return result


async def run(args):
    if getattr(args, 'pending_only', False):
        try:
            from .holder_pending_schema import run_pending
        except ImportError:
            from holder_pending_schema import run_pending
        return await run_pending(args)
    cfg = load_config(args.config)
    lock = acquire_instance_lock() if args.apply else None
    engine, client = make_engine(cfg['mysql']), create_client(cfg['redis'])
    prefix = cfg['redis'].get('namespace', 'empire')
    result = dict(checked_at=datetime.now(UTC).isoformat(), applied=False,
                  ddl_sha256=hashlib.sha256(Path('sql/schema.sql').read_bytes()).hexdigest())
    try:
        result['pending'] = await client.xlen(prefix + ':ingest')
        if args.apply and result['pending']:
            raise ValueError('共享待归档非零，拒绝结构维护')
        with engine.connect() as conn:
            if conn.execute(text("SELECT GET_LOCK('empire-business-schema-v2',0)")).scalar_one() != 1:
                raise ValueError('结构维护锁忙')
            conn.commit()
            try:
                result['before'] = inventory(conn)
                try:
                    validate_shapes(conn, ['holder_report', 'holder_member'])
                    inventory(conn, verify=True)
                    result['already_current'] = True
                except (RuntimeError, ValueError):
                    result['already_current'] = False
                if args.apply and not result['already_current']:
                    head_columns = {r['name'] for r in inspect(conn).get_columns('holder_report')}
                    if 'quality_flags' not in head_columns:
                        conn.exec_driver_sql('ALTER TABLE holder_report ADD quality_flags SMALLINT NOT NULL DEFAULT 0 AFTER ratio_basis')
                        conn.commit()
                    conn.exec_driver_sql('ALTER TABLE holder_report ALTER quality_flags DROP DEFAULT')
                    conn.commit()
                    columns = {r['name'] for r in inspect(conn).get_columns('holder_member')}
                    if 'source_rank' not in columns:
                        conn.exec_driver_sql('ALTER TABLE holder_member ADD source_rank SMALLINT NULL AFTER seq')
                        conn.commit()
                    conn.commit()
                    with conn.begin():
                        conn.execute(text("UPDATE holder_member m JOIN holder_report r ON r.report_key=m.report_key SET m.source_rank=m.seq WHERE r.kind='bond_holders' AND m.source_rank IS NULL"))
                    for table, checks in (('holder_report', ('ck_holder_counts', 'ck_holder_totals', 'ck_holder_report_type')),
                                          ('holder_member', ('ck_holder_member_group', 'ck_holder_member_values', 'ck_holder_member_precision'))):
                        clauses = []
                        for check in checks:
                            declaration = next(line.strip().rstrip(',') for line in ddl(table).splitlines() if 'CONSTRAINT ' + check + ' ' in line)
                            clauses.extend(['DROP CHECK ' + check, 'ADD ' + declaration])
                        if table == 'holder_member':
                            clauses.extend(['MODIFY ratio DECIMAL(9,4) NULL', 'MODIFY quantity DECIMAL(24,4) NULL',
                                            'MODIFY quantity_scale BIGINT NULL', 'MODIFY quantity_decimals SMALLINT NULL'])
                        conn.exec_driver_sql('ALTER TABLE ' + table + ' ' + ','.join(clauses))
                        conn.commit()
                    conn.commit()
                    # One transaction covers all re-identification and hashes;
                    # DDL is additive and may already exist on a safe retry.
                    with conn.begin():
                        for batch in batches(conn):
                            updated, replacements = [], []
                            for head, members in batch:
                                row = normalized(head, members)
                                validate(row['kind'], row['unified_code'], [row])
                                key = head['report_key']
                                if digest(row) != head['content_hash']:
                                    updated.append((key, digest(row)))
                                if any(m['seq'] != n['seq'] for m,n in zip(members,row['members'])):
                                    replacements.append((key, row['members']))
                            if replacements:
                                params = {'k'+str(i): key for i,(key,_) in enumerate(replacements)}
                                conn.execute(text('DELETE FROM holder_member WHERE report_key IN (' + ','.join(':'+k for k in params) + ')'), params)
                                names = ('report_key', *MEMBER_FIELDS)
                                conn.execute(text('INSERT INTO holder_member(' + ','.join(names) + ') VALUES(' + ','.join(':' + n for n in names) + ')'), [{**m, 'report_key': key} for key,body in replacements for m in body])
                            if updated:
                                params = {k+str(i): v for i,(key,checksum) in enumerate(updated) for k,v in [('k',key),('h',checksum)]}
                                conn.execute(text('UPDATE holder_report SET content_hash=CASE report_key ' + ' '.join('WHEN :k'+str(i)+' THEN :h'+str(i) for i in range(len(updated))) + ' END WHERE report_key IN (' + ','.join(':k'+str(i) for i in range(len(updated))) + ')'), params)
                        # The former contract cannot prove the upgraded window.
                        conn.execute(text('DELETE FROM collection_state WHERE namespace=:ns AND project_id=\'ths-holders\''), {'ns': prefix})
                    validate_shapes(conn, ['holder_report', 'holder_member'])
                result['after'] = inventory(conn, verify=args.apply)
                if result['before'] != result['after']:
                    raise ValueError('来源事实、总量或观测版本变化，拒绝确认迁移')
                if args.apply:
                    cache = FingerprintCache(SimpleNamespace(client=client, prefix=prefix), cfg.get('archive', {}), lambda _: HolderDataset.FINGERPRINT_VERSION)
                    await cache.invalidate('ths_holders', 'ths')
                    await client.delete(prefix + ':checkpoint:ths-holders-v1', prefix + ':archive:progress:ths-holders-v1')
                    result.update(applied=True, facts_preserved=True, proof_rebuild_required=True)
            finally:
                conn.execute(text("SELECT RELEASE_LOCK('empire-business-schema-v2')"))
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', 'utf8')
        print('PASS holder source rows maintenance', result['applied'])
    finally:
        engine.dispose()
        await client.aclose()
        if lock:
            lock.unlock()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config')
    p.add_argument('--apply', action='store_true')
    p.add_argument('--pending-only', action='store_true', help='仅无损转换待归档schema4到5，不改SQL或覆盖证明')
    p.add_argument('--report', required=True)
    args = p.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
