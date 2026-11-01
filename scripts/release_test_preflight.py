"""Fail before the suite when private SQL or shared Redis is unavailable."""
import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

from empire.core.config import load_config
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client


def settings(path):
    if not path:
        raise ValueError('Set EMPIRE_TEST_MYSQL_SETTINGS to the private MySQL configuration')
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if type(value.get('port')) is not int or value['port'] != 13348:
        raise ValueError('Release tests require the independent MySQL on port 13348')
    return {**value, 'connect_timeout': 5}


def sql_check(production, test):
    source = make_engine({**production, 'connect_timeout': 5})
    target = make_engine({**test, 'database': None})
    name = 'empire_preflight_' + uuid4().hex + '_test'
    try:
        with source.connect() as conn:
            production_id = conn.exec_driver_sql('SELECT @@server_uuid').scalar_one()
        with target.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
            identity, port = conn.exec_driver_sql('SELECT @@server_uuid,@@port').one()
            if not identity or identity == production_id or port != 13348:
                raise ValueError('Private SQL identity/port does not match the test contract')
            created = False
            try:
                conn.exec_driver_sql(f'CREATE DATABASE `{name}`')
                created = True
                conn.exec_driver_sql(f'CREATE TABLE `{name}`.probe (id INT PRIMARY KEY) ENGINE=InnoDB')
                conn.exec_driver_sql(f'INSERT INTO `{name}`.probe VALUES (1)')
                if conn.exec_driver_sql(f'SELECT id FROM `{name}`.probe').scalar_one() != 1:
                    raise ValueError('Private SQL round trip failed')
            finally:
                if created:
                    conn.exec_driver_sql(f'DROP DATABASE `{name}`')
    finally:
        source.dispose()
        target.dispose()


async def redis_check(config):
    client = create_client(config)
    try:
        async with asyncio.timeout(5):
            await client.ping()
    finally:
        await client.aclose()


def main():
    stage = 'settings'
    try:
        test = settings(os.environ.get('EMPIRE_TEST_MYSQL_SETTINGS'))
        cfg = load_config()
        stage = 'private-sql-identity-and-permissions'
        sql_check(cfg['mysql'], test)
        stage = 'redis-ping'
        asyncio.run(redis_check(cfg['redis']))
    except Exception:
        # Driver/config exceptions can contain credentials or connection URLs.
        raise SystemExit('FAIL release test preflight: ' + stage +
                         '; verify the private 13348 instance and configured Redis') from None
    print('PASS test preflight: independent SQL, create/read/write/drop permissions, Redis ping')


if __name__ == '__main__':
    main()
