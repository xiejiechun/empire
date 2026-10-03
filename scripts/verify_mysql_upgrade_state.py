"""Run affected state/archive regressions on a separate MySQL server, never the application DB."""
import argparse
import copy
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest

import empire.core.config as config
from empire.plugins.infra.mysql_store import initialize_database, make_engine


def run(settings_path, output):
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    original = config.load_config
    cfg = original()
    settings = json.loads(Path(settings_path).read_text(encoding='utf-8'))
    production = cfg['mysql']
    if (settings.get('host', '127.0.0.1'), settings.get('port', 3306)) == (
            production.get('host', '127.0.0.1'), production.get('port', 3306)):
        raise ValueError('专项验证必须使用独立 MySQL 实例')
    database = 'empire_' + uuid4().hex + '_upgrade_drill'
    admin = make_engine(settings)
    created = False
    previous_opt_in = os.environ.get('EMPIRE_INTEGRATION')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin')
            created = True
        settings['database'] = database
        initialize_database(settings)
        cfg['mysql'] = settings
        cfg['redis']['namespace'] = 'empire:test:upgrade:' + uuid4().hex

        def isolated(path=None):
            if path is not None:
                return original(path)
            return copy.deepcopy(cfg)

        config.load_config = isolated
        os.environ['EMPIRE_INTEGRATION'] = '1'
        return pytest.main([
            str(root / 'tests/integration/test_financial_archive.py'),
            str(root / 'tests/integration/test_capital_archive.py'),
            str(root / 'tests/integration/test_issue_availability_archive.py'),
            '-q', '--tb=short', '-o', 'faulthandler_timeout=60',
            '--basetemp=' + str(output / 'pytest'), '--junitxml=' + str(output / 'pipeline.xml'),
        ])
    finally:
        config.load_config = original
        if previous_opt_in is None:
            os.environ.pop('EMPIRE_INTEGRATION', None)
        else:
            os.environ['EMPIRE_INTEGRATION'] = previous_opt_in
        if created:
            assert database.endswith('_upgrade_drill') and settings['database'] == database
            with admin.connect() as conn:
                conn.exec_driver_sql(f'DROP DATABASE `{database}`')
        admin.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', required=True, help='独立 MySQL 连接设置 JSON；不要提交真实凭据')
    parser.add_argument('--output', default='build/mysql-upgrade-20261003/state-regression')
    args = parser.parse_args()
    raise SystemExit(run(args.settings, args.output))
