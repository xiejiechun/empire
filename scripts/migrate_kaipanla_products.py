"""Explicit stopped-app split: verify every source row before retiring its old copy."""
import argparse
import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text

from empire.core.config import load_config
from empire.core.redaction import Redactor
from empire.plugins.collectors.kaipanla_kinds import PRODUCTS, project
from empire.plugins.datasets.intraday import digest as old_digest
from empire.plugins.datasets.intraday import validate as validate_old
from empire.plugins.datasets.kaipanla_products import digest, validate
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client


def split(row):
    validate_old(row)
    for index, kind in enumerate(('trend', 'auction')):
        code = row['source_codes'][index]
        value = dict(kind=kind, code=row['code'], market=row['market'], trade_date=row['trade_date'],
            source_code=code, aliases={code: row['aliases'][code]} if code != row['code'] else {},
            lifecycle=row['lifecycle'], data={PRODUCTS[kind].field: row[kind], 'preclose_px': row['preclose_px']},
            metadata={'time': row['source_times'][index]})
        validate(value, kind)
        yield value


def migrate(engine, namespace, *, apply=False):
    report = {'old_rows': 0, 'verified_products': 0, 'applied': apply, 'old_table_dropped': False}
    with engine.connect() as conn:
        if not inspect(conn).has_table('stock_intraday'):
            report['old_table_absent'] = True
            return report
    if not apply:
        with engine.connect() as conn:
            records = conn.execute(text('SELECT unified_code,trade_date,payload,content_hash FROM stock_intraday '
                'ORDER BY unified_code,trade_date')).mappings()
            for stored in records:
                row = json.loads(stored['payload']) if isinstance(stored['payload'], str) else stored['payload']
                if old_digest(row) != stored['content_hash'] or (row['code'] + '.' + row['market'], row['trade_date']) != (
                        stored['unified_code'], stored['trade_date'].isoformat()):
                    raise ValueError('旧业务关联或摘要损坏，拒绝迁移')
                list(split(row))
                report['old_rows'] += 1
        return report
    ddl = re.search(r'CREATE TABLE IF NOT EXISTS stock_market_day \(.*?;',
        (Path(__file__).resolve().parents[1] / 'sql/schema.sql').read_text('utf-8'), re.S)[0]
    with engine.begin() as conn:
        conn.exec_driver_sql(ddl)
    # Keyset batches remain bounded; old rows are retired only after both new
    # snapshots are read back, including exact business content and version.
    while True:
        with engine.begin() as conn:
            records = conn.execute(text('SELECT unified_code,trade_date,payload,content_hash,version_observed_at '
                'FROM stock_intraday ORDER BY unified_code,trade_date LIMIT 100 FOR UPDATE')).mappings().all()
            if not records:
                break
            for stored in records:
                row = json.loads(stored['payload']) if isinstance(stored['payload'], str) else stored['payload']
                if old_digest(row) != stored['content_hash'] or (row['code'] + '.' + row['market'], row['trade_date']) != (
                        stored['unified_code'], stored['trade_date'].isoformat()):
                    raise ValueError('旧业务关联或摘要损坏')
                for value in split(row):
                    params = dict(kind=value['kind'], security=stored['unified_code'], day=stored['trade_date'])
                    old = conn.execute(text('SELECT payload,content_hash,version_observed_at FROM stock_market_day '
                        'WHERE kind=:kind AND unified_code=:security AND trade_date=:day FOR UPDATE'), params).mappings().first()
                    if old:
                        prior = json.loads(old['payload']) if isinstance(old['payload'], str) else old['payload']
                        if prior != value or old['content_hash'] != digest(value) or old['version_observed_at'] != stored['version_observed_at']:
                            raise ValueError('新旧数据冲突，拒绝覆盖或清理旧记录')
                    else:
                        conn.execute(text('INSERT INTO stock_market_day(kind,unified_code,trade_date,payload,content_hash,version_observed_at) '
                            'VALUES(:kind,:security,:day,:payload,:hash,:version)'),
                            {**params, 'payload': json.dumps(value, ensure_ascii=False), 'hash': digest(value),
                             'version': stored['version_observed_at']})
                    actual = conn.execute(text('SELECT payload,content_hash,version_observed_at FROM stock_market_day '
                        'WHERE kind=:kind AND unified_code=:security AND trade_date=:day'), params).mappings().one()
                    body = json.loads(actual['payload']) if isinstance(actual['payload'], str) else actual['payload']
                    if body != value or actual['content_hash'] != digest(value) or actual['version_observed_at'] != stored['version_observed_at']:
                        raise ValueError('迁移读回验证失败')
                    report['verified_products'] += 1
                conn.execute(text('DELETE FROM stock_intraday WHERE unified_code=:security AND trade_date=:day'),
                             dict(security=stored['unified_code'], day=stored['trade_date']))
                report['old_rows'] += 1
    with engine.begin() as conn:
        conn.execute(text('DELETE FROM collection_state WHERE namespace=:namespace AND project_id=:project'),
                     dict(namespace=namespace, project='kaipanla-intraday'))
        conn.execute(text("DELETE FROM app_setting WHERE namespace=:namespace AND kind='task' AND setting_key=:key"),
                     dict(namespace=namespace, key='kaipanla-intraday'))
        # No old schedule inheritance. Existing explicitly saved new policies
        # are respected on a repeated maintenance run.
        from empire.plugins.infra.settings import SettingsStore
        settings = SettingsStore(None, namespace)
        for kind in PRODUCTS:
            exists = conn.execute(text("SELECT 1 FROM app_setting WHERE namespace=:namespace AND kind='task' AND setting_key=:key"),
                                  dict(namespace=namespace, key=project(kind))).first()
            if not exists:
                settings.save_in_transaction(conn, 'task', project(kind), dict(enabled=False, mode='manual',
                    interval_seconds=86400, daily_time='18:00', request_retries=2, use_proxy=True, proxy_fallback=True))
    # DDL commits implicitly in MySQL. Recheck after all conversion transactions;
    # never drop a table containing unconverted business data.
    with engine.connect() as conn:
        if conn.execute(text('SELECT 1 FROM stock_intraday LIMIT 1')).first():
            raise ValueError('旧表仍有业务数据，拒绝删除')
        conn.exec_driver_sql('DROP TABLE stock_intraday')
        if inspect(conn).has_table('stock_intraday'):
            raise ValueError('旧表删除验证失败')
        report['old_table_dropped'] = True
    return report


async def run(args):
    from PySide6.QtCore import QCoreApplication

    from empire.__main__ import acquire_instance_lock
    app = QCoreApplication.instance() or QCoreApplication([])
    lock = acquire_instance_lock()  # Hold the normal singleton lock throughout.
    cfg = load_config(args.config)
    redactor = Redactor.from_config(cfg)
    namespace = cfg['redis'].get('namespace', 'empire')
    client, engine = create_client(cfg['redis']), make_engine(cfg['mysql'])
    try:
        if await client.xlen(namespace + ':ingest'):
            raise RuntimeError('待归档队列不为空，先通过原归档器处理；不清队跳过')
        report = migrate(engine, namespace, apply=args.apply)
        if args.apply:
            key = namespace + ':collection:control:v1'
            raw = await client.get(key)
            if raw:
                control = json.loads(raw)
                control.get('jobs', {}).pop('kaipanla-intraday', None)
                await client.set(key, json.dumps(control, ensure_ascii=False))
            # Retire only the exact obsolete source fingerprint/checkpoint keys.
            prefix = namespace + ':archive:fingerprints:v1:kaipanla_intraday_v1:kaipanla'
            await client.delete(prefix, prefix + ':expiry', namespace + ':checkpoint:kaipanla-intraday-v1')
        report.update(captured_at=datetime.now(UTC).isoformat(), new_tasks_default_disabled=True,
                      full_history_collection_started=False)
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))
    except Exception as exc:
        print(redactor.text(exc), file=sys.stderr)
        return 1
    finally:
        engine.dispose()
        await client.aclose()
        lock.unlock()
        del app
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report', default='build/kaipanla-products-migration.json')
    raise SystemExit(asyncio.run(run(parser.parse_args())))
