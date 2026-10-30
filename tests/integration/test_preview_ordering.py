"""Every advertised sort column compiles through its formal service on MySQL.

The integration fixture owns and guards a UUID schema. No collectors, archive
workers, production DDL, or source requests are started here.
"""

import os
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.desktop_bridge.preview import catalog, read
from empire.desktop_bridge.preview_catalog import views
from empire.plugins.infra.collection_state import save_state
from empire.plugins.infra.mysql_store import make_engine

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Private MySQL opt-in')]


async def test_every_advertised_sql_sort_column():
    cfg = load_config()
    manager = build_manager(cfg)
    engine = make_engine(cfg['mysql'])

    async def execute(fn, *args):
        return fn(*args)

    def get(capability):
        service = manager.entries[manager.providers[capability]].plugin
        service.mysql = SimpleNamespace(read_engine=engine, read=execute)
        return service

    failures, checked = [], 0
    try:
        stock = get('stocks.query')
        with engine.begin() as conn:
            save_state(conn, stock.namespace, 'ths-stocks', 'ths', 'stocks',
                       dict(version='2026-10-29', publication={'completed_at': '2026-10-29'}), {})
            conn.execute(text("INSERT INTO theme_detail(theme_id,name,brief,introduction,observed_at,content_sha256) "
                              "VALUES ('1','测试题材','','','2026-10-29',:hash)"), {'hash': 'a' * 64})
        registry = SimpleNamespace(get=get)
        for task in manager.entries['collection.control'].plugin.definitions:
            for declaration, spec in zip(views(task), catalog(task), strict=True):
                if spec['sort_scope'] != 'filtered' or declaration.mode == 'live':
                    continue
                filters = {key: value for key, value in {
                    'security': '000001.SZ', 'theme_id': '1', 'day': '2026-10-29',
                }.items() if key in declaration.filters}
                for column in spec['columns']:
                    for direction in ('asc', 'desc'):
                        order = dict(field=column['key'], direction=direction)
                        try:
                            result = await read(registry, task, declaration.id, filters, order=order)
                            assert result['next'] is None
                            checked += 1
                        except Exception as exc:
                            failures.append((task, declaration.id, order, str(exc)))
        assert not failures, '\n'.join(str(failure) for failure in failures)
        assert checked > 1000
    finally:
        engine.dispose()
