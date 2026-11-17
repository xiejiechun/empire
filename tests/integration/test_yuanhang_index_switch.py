"""Explicit replacement preserves unrelated data and can resume after DDL."""
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text

from empire.core.config import load_config
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.settings import SettingsStore
from scripts import switch_yuanhang_indices as migration

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Private SQL opt-in')]


async def test_switch_guard_migrate_preserve_and_repeat(tmp_path, monkeypatch):
    cfg = load_config()
    cfg['redis']['namespace'] = 'empire:test:' + uuid4().hex
    namespace = cfg['redis']['namespace']
    lock = Mock()
    monkeypatch.setattr(migration, 'acquire_instance_lock', lambda: lock)
    engine, client = make_engine(cfg['mysql']), create_client(cfg['redis'])
    policy = dict(enabled=True, mode='interval', interval_seconds=900, daily_time='18:00', request_retries=2)
    try:
        with engine.begin() as conn:
            for table in migration.OLD_TABLES:
                conn.exec_driver_sql(f'CREATE TABLE `{table}` (id INT PRIMARY KEY)')
                conn.exec_driver_sql(f'INSERT INTO `{table}` VALUES (1)')
            conn.exec_driver_sql("INSERT INTO stock(unified_code,name) VALUES ('000001.SZ','保留')")
            settings = SettingsStore(None, namespace)
            settings.save_in_transaction(conn, 'task', 'ths-indices', policy)
            settings.save_in_transaction(conn, 'task', 'ths-index-prices', policy)
            settings.save_in_transaction(conn, 'task', migration.MEMBER_PROJECT, {**policy, 'interval_seconds': 1200})
        await client.set(namespace+':unrelated', 'preserved')
        plan = tmp_path/'plan.json'
        args = SimpleNamespace(report=str(plan), apply=False, plan=None)
        report = await migration.switch(cfg, args)
        assert all(v == 1 for v in report['old_tables'].values())
        # Pending messages forbid all DDL, even when the plan was made empty.
        await client.xadd(namespace+':ingest', {'test': 'pending'})
        args = SimpleNamespace(report=str(tmp_path/'refused.json'), apply=True, plan=str(plan))
        with pytest.raises(ValueError, match='未清零'):
            await migration.switch(cfg, args)
        await client.delete(namespace+':ingest')
        args.report = str(tmp_path/'applied.json')
        result = await migration.switch(cfg, args)
        assert result['applied'] and result['unrelated_business_unchanged']
        with engine.connect() as conn:
            assert not set(migration.OLD_TABLES) & set(inspect(conn).get_table_names())
            assert conn.exec_driver_sql('SELECT COUNT(*) FROM stock').scalar_one() == 1
            rows = conn.execute(text("SELECT setting_key,payload FROM app_setting WHERE namespace=:ns AND kind='task'"), dict(ns=namespace))
            saved = {k: json.loads(v) if isinstance(v, str) else v for k, v in rows}
            assert saved[migration.MEMBER_PROJECT]['interval_seconds'] == 1200
            assert saved[migration.PRICE_PROJECT]['interval_seconds'] == 900
            assert saved['ths-indices']['archived'] and not saved['ths-indices']['enabled']
        assert await client.get(namespace+':unrelated') == 'preserved'
        args.report = str(tmp_path/'repeat.json')
        assert (await migration.switch(cfg, args))['applied']
        assert lock.unlock.call_count == 3
    finally:
        engine.dispose()
        keys = [k async for k in client.scan_iter(match=namespace+':*')]
        if keys:
            await client.delete(*keys)
        await client.aclose()
