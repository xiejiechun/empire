"""Every integration test owns a private schema; never isolate business using fake sources."""
import copy
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

import empire.core.config as config
from empire.plugins.infra.mysql_store import initialize_database, make_engine


@pytest.fixture(autouse=True)
def private_business_database(request, monkeypatch):
    if os.environ.get('EMPIRE_INTEGRATION') != '1' or request.module.__name__.endswith('test_state_unit_isolated'):
        yield
        return
    original = config.load_config
    cfg = copy.deepcopy(original())
    settings_path = os.environ.get('EMPIRE_TEST_MYSQL_SETTINGS')
    if settings_path:
        cfg['mysql'] = json.loads(Path(settings_path).read_text(encoding='utf-8'))
    settings = copy.deepcopy(cfg['mysql'])
    admin = make_engine(settings)
    database = 'empire_' + uuid4().hex + '_test'
    created = False
    guarded = False

    def require_owned_database(conn, cursor, statement, parameters, context, executemany):
        if conn.engine.url.database != database:
            raise RuntimeError('Integration SQL target is not this test-owned database')
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin')
            created = True
        cfg['mysql']['database'] = database
        cfg['redis']['namespace'] = 'empire:test:' + uuid4().hex
        initialize_database(cfg['mysql'])
        # Protect every engine, including stale imported factories/config functions.
        event.listen(Engine, 'before_cursor_execute', require_owned_database)
        guarded = True

        def isolated(path=None):
            return copy.deepcopy(cfg)

        monkeypatch.setattr(config, 'load_config', isolated)
        if hasattr(request.module, 'load_config'):
            monkeypatch.setattr(request.module, 'load_config', isolated)
        # Imported shared fixtures retain their defining module globals.
        import sys
        for name, module in tuple(sys.modules.items()):
            if (getattr(module, '__file__', None) and
                    Path(module.__file__).resolve().parent == Path(__file__).resolve().parent and
                    hasattr(module, 'load_config')):
                monkeypatch.setattr(module, 'load_config', isolated)
        yield
    finally:
        if guarded:
            event.remove(Engine, 'before_cursor_execute', require_owned_database)
        if created:
            assert database.endswith('_test') and cfg['mysql']['database'] == database
            with admin.connect() as conn:
                conn.exec_driver_sql(f'DROP DATABASE `{database}`')
        admin.dispose()
