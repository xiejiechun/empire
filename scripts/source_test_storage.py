"""Shared private verification storage; never a production writer."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from empire.contracts.security import split_unified_code
from empire.core.config import resource_root
from empire.plugins.infra.mysql_store import initialize_database, make_engine
from empire.plugins.infra.redis_store import create_client

DELETE_OWNED = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return redis.error_reply('owner mismatch') end
for i = 2, #KEYS do
  if KEYS[i] == KEYS[1] or string.sub(KEYS[i], 1, string.len(ARGV[2])) ~= ARGV[2] then
    return redis.error_reply('foreign key')
  end
end
local n = 0
for i = 2, #KEYS do n = n + redis.call('UNLINK', KEYS[i]) end
return n
"""
DELETE_OWNER = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return redis.error_reply('owner mismatch') end
return redis.call('DEL', KEYS[1])
"""


def ensure_separate_server(production: str, test: str) -> None:
    if not production or not test or production.casefold() == test.casefold():
        raise ValueError('测试与生产 MySQL 必须是不同 server_uuid；不接受主机别名隔离')


def test_settings(value: dict) -> dict:
    if not isinstance(value, dict) or value.get('port') != 13348 or type(value.get('port')) is not int:
        raise ValueError('必须显式提供端口为 13348 的独立测试 MySQL 配置')
    if not isinstance(value.get('host'), str) or not value['host'].strip():
        raise ValueError('测试 MySQL host 缺失')
    if not isinstance(value.get('user'), str) or not value['user'].strip():
        raise ValueError('测试 MySQL user 缺失')
    if not isinstance(value.get('password', ''), str):
        raise ValueError('测试 MySQL password 类型错误')
    # Supplied database is never used as a write/drop target.
    return {key: value[key] for key in ('host', 'port', 'user', 'password', 'connect_timeout') if key in value}


def read_server_uuid(settings: dict) -> str:
    engine = make_engine(settings)
    try:
        with engine.connect() as conn:
            return str(conn.execute(text('SELECT @@server_uuid')).scalar_one())
    finally:
        engine.dispose()


def read_pool(config: dict) -> dict:
    """All production SQL is confined to one read-only transaction, closed here."""
    engine = make_engine(config['mysql'])
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql('START TRANSACTION READ ONLY')
            try:
                server = str(conn.execute(text('SELECT @@server_uuid')).scalar_one())
                stocks = [dict(row) for row in conn.execute(text(
                    'SELECT unified_code,name FROM stock ORDER BY unified_code LIMIT 15001')).mappings()]
                if not stocks or len(stocks) > 15000:
                    raise ValueError('正式股票池为空或超限')
                identities = [row['unified_code'] for row in stocks]
                if len(identities) != len(set(identities)):
                    raise ValueError('正式股票池重复')
                for row in stocks:
                    split_unified_code(row['unified_code'])
                    if not isinstance(row['name'], str) or not row['name'].strip():
                        raise ValueError('正式股票池名称无效')
                settings = [dict(row) for row in conn.execute(text(
                    "SELECT kind,setting_key,payload FROM app_setting WHERE namespace=:ns AND "
                    "((kind='site' AND setting_key='ths') OR (kind='download' AND setting_key='global'))"),
                    {'ns': config['redis']['namespace']}).mappings()]
                for row in settings:
                    if isinstance(row['payload'], str):
                        row['payload'] = json.loads(row['payload'])
                return {'server_uuid': server, 'stocks': stocks, 'settings': settings}
            finally:
                conn.rollback()
    finally:
        engine.dispose()


SQL_TOKENS = re.compile(r"'(?:''|\\.|[^'])*'|\"(?:\"\"|\\.|[^\"])*\"|`(?:``|[^`])*`|"
                        r'--[^\n]*|/\*.*?\*/|[A-Za-z_][A-Za-z_0-9]*|[^\s]', re.S)
METADATA_TABLES = {'tables', 'columns', 'statistics', 'key_column_usage', 'table_constraints',
                   'referential_constraints', 'check_constraints', 'schemata'}


def initial_schema_statements() -> set[tuple[str, ...]]:
    """Only the exact checked-in initializer forms, never arbitrary DDL."""
    schema = (resource_root() / 'sql' / 'schema.sql').read_text(encoding='utf-8')
    schema = '\n'.join(line for line in schema.splitlines() if not line.lstrip().startswith('--'))
    return {tuple(SQL_TOKENS.findall(value)) for value in schema.split(';') if value.strip()}


def check_business_statement(statement: str, database: str = '') -> None:
    """Guard current formal SQL shapes, not a general-purpose SQL parser."""
    raw = SQL_TOKENS.findall(statement)
    if any(token.startswith(('--', '/*')) or token == '#' for token in raw):
        raise ValueError('测试业务 SQL 不接受注释中的隐藏语句')
    tokens = [('<literal>' if token.startswith(("'", '"')) else token.strip('`').lower()) for token in raw]
    if not tokens or ';' in tokens or tokens[0] == 'use':
        raise ValueError('测试业务连接禁止切库及多语句')
    command = tokens[0]
    read = command in {'select', 'show', 'describe'}
    if command == 'create':
        # The explicit initializer only creates unqualified tables in the owned
        # session. LIKE/AS SELECT/foreign REFERENCES and storage options cannot
        # be smuggled through an additional generic CREATE grammar.
        if tuple(raw) not in initial_schema_statements():
            raise ValueError('测试业务 CREATE 仅接受当前 schema.sql 的精确初始化语句')
        return
    if command in {'alter', 'drop', 'replace'}:
        raise ValueError('测试业务连接不需要 ALTER/DROP/REPLACE；清理由归属核实后的管理连接执行')
    if command == 'insert' and tokens[1:2] != ['into']:
        raise ValueError('测试业务 INSERT 必须显式使用 INTO')
    if command == 'update' and tokens[1:2] in (['low_priority'], ['ignore']):
        raise ValueError('测试业务 UPDATE 不接受额外修饰符')
    if command == 'delete' and (tokens[1:2] != ['from'] or 'using' in tokens):
        raise ValueError('测试业务 DELETE 仅接受单表 FROM 形式')

    def table(index, *, metadata=False):
        if index >= len(tokens) or not re.fullmatch('[a-z_][a-z_0-9]*', tokens[index]):
            raise ValueError('无法核实 SQL 表归属')
        if index + 1 < len(tokens) and tokens[index + 1] == '.':
            schema = tokens[index]
            if index + 2 >= len(tokens):
                raise ValueError('SQL 表名不完整')
            name = tokens[index + 2]
            if not re.fullmatch('[a-z_][a-z_0-9]*', name):
                raise ValueError('SQL 表名无效')
            if not (schema == database.lower() and database or
                    metadata and schema == 'information_schema' and name in METADATA_TABLES):
                raise ValueError('测试业务 SQL 禁止跨库访问；只例外允许必要的只读系统 metadata')
            if index + 3 < len(tokens) and tokens[index + 3] == '.':
                raise ValueError('SQL 表限定名层次无效')
            return index + 3
        return index + 1

    if command == 'show':
        if tokens[1:3] == ['create', 'table']:
            if table(3) != len(tokens):
                raise ValueError('SHOW CREATE TABLE 不接受额外子句')
        elif tokens[1:4] == ['full', 'tables', 'from']:
            if len(tokens) != 5 or tokens[4] != database.lower() or not database:
                raise ValueError('SHOW TABLES 仅允许当前测试库')
        elif not (tokens[1:2] in (['variables'], ['collation']) and
                  (len(tokens) == 2 or tokens[2:] == ['like', '<literal>'])):
            raise ValueError('测试业务连接仅支持必要的 SHOW metadata')
        return
    if command == 'describe':
        if table(1) != len(tokens):
            raise ValueError('DESCRIBE 仅允许完整表名')
        return
    if re.fullmatch(r"SET time_zone\s*=\s*'\+08:00'", statement.strip(), re.I):
        return
    if command not in {'select', 'insert', 'update', 'delete'}:
        raise ValueError('测试业务连接拒绝未知语句')
    if set(tokens) & {'with', 'table', 'explain', 'handler', 'load', 'call', 'lateral', 'load_file'}:
        # CTEs, TABLE query expressions and alternate relation/function forms
        # are unused by the holder/financial paths and need separate review.
        raise ValueError('测试业务连接拒绝未经覆盖的 SQL 形式')
    depth, relations = 0, set()
    for index, token in enumerate(tokens):
        if token == '(':
            depth += 1
        elif token == ')':
            relations.discard(depth)
            depth -= 1
        elif token in {'where', 'group', 'order', 'having', 'limit', 'union', 'set', 'values'}:
            relations.discard(depth)
        elif token == ',' and depth in relations:
            # Existing queries use JOIN; comma lists can hide secondary targets.
            raise ValueError('测试业务连接拒绝逗号多表语句')
        elif token == 'references':
            table(index + 1)
        elif token in {'from', 'join', 'straight_join'} or (token == 'update' and index == 0):
            relations.add(depth)
            if tokens[index + 1:index + 2] == ['(']:
                if tokens[index + 2:index + 3] != ['select']:
                    raise ValueError('测试业务括号关系仅允许 SELECT 子查询')
            else:
                table(index + 1, metadata=read)
        elif token == 'into':
            if read:
                raise ValueError('测试 SELECT 禁止 INTO 写入')
            table(index + 1)
        elif token == 'table' and index == 1:
            following = index + 1
            if tokens[following:following + 3] == ['if', 'not', 'exists']:
                following += 3
            table(following)
        elif token == '.' and index + 2 < len(tokens) and tokens[index + 2] == '(':
            raise ValueError('测试业务 SQL 禁止跨 schema 函数调用')


@dataclass
class PrivateStorage:
    mysql: dict
    redis: dict
    run_id: str
    owner: str
    production_uuid: str

    def __post_init__(self) -> None:
        if not re.fullmatch('[0-9a-f]{32}', self.run_id) or not re.fullmatch('[0-9a-f]{64}', self.owner):
            raise ValueError('验证资源身份无效')
        self.database = 'empire_verify_ths_' + self.run_id + '_test'
        self.namespace = 'empire:test:verify_ths:' + self.run_id
        self.owner_key = self.namespace + ':verifier-owner'
        self.owner_hash = hashlib.sha256(self.owner.encode()).hexdigest()
        self.settings = {**test_settings(self.mysql), 'database': self.database}
        self.engine = self.conn = self.client = None
        self.server_uuid = ''
        self.created = self.marked = self.redis_owned = self.locked = self.guarded = False
        self.redis_residual = False
        self.sql_unverified = self.redis_unverified = False

    def identity(self) -> dict:
        return dict(database=self.database, namespace=self.namespace, run_id=self.run_id,
                    server_uuid=self.server_uuid, owner_sha256=self.owner_hash)

    def create_sql(self, before_create=None) -> None:
        self.engine = make_engine({**self.settings, 'database': None}, pool_size=1)
        self.conn = self.engine.connect()
        self.server_uuid = str(self.conn.execute(text('SELECT @@server_uuid')).scalar_one())
        ensure_separate_server(self.production_uuid, self.server_uuid)
        self.locked = self.conn.execute(text('SELECT GET_LOCK(:name,0)'), {'name': self.database}).scalar_one() == 1
        if not self.locked:
            raise RuntimeError('测试库独占锁已被占用')
        if before_create is not None:
            before_create()
        self.sql_unverified = True
        self.conn.execute(text(f'CREATE DATABASE `{self.database}` CHARACTER SET utf8mb4'))
        self.created = True
        self.conn.execute(text(f'CREATE TABLE `{self.database}`._empire_verifier_owner '
                               '(id INT PRIMARY KEY,run_id VARCHAR(32),owner_hash VARCHAR(64),'
                               'server_uuid VARCHAR(64),database_name VARCHAR(64)) ENGINE=InnoDB'))
        self.conn.execute(text(f'INSERT INTO `{self.database}`._empire_verifier_owner VALUES '
                               '(1,:run,:owner,:server,:database)'), dict(run=self.run_id,
                               owner=self.owner_hash, server=self.server_uuid, database=self.database))
        self.conn.commit()
        self.marked = True
        self.sql_unverified = False
        event.listen(Engine, 'before_cursor_execute', self.guard)
        self.guarded = True

    def guard(self, conn, cursor, statement, parameters, context, executemany) -> None:
        if conn.engine is self.engine:
            return
        if conn.engine.url.database != self.database:
            raise ValueError('测试业务连接只能使用本轮独占数据库')
        # Read the actual session identity, not only engine.url (which misses USE).
        raw = conn.connection.cursor()
        try:
            raw.execute('SELECT @@server_uuid,DATABASE()')
            server, database = raw.fetchone()
        finally:
            raw.close()
        if (server, database) != (self.server_uuid, self.database):
            raise ValueError('测试业务连接实际实例或数据库发生变化')
        check_business_statement(statement, self.database)

    async def create_redis(self) -> None:
        self.client = create_client(self.redis)
        async for _ in self.client.scan_iter(match=self.namespace + ':*', count=100):
            self.redis_residual = True
            raise ValueError('测试 Redis namespace 已存在')
        self.redis_unverified = True
        if not await self.client.set(self.owner_key, self.owner, nx=True):
            self.redis_residual = True
            raise ValueError('测试 Redis owner 已存在')
        self.redis_owned = True
        self.redis_unverified = False

    def attach_sql(self, expected_server: str) -> None:
        """Recover an existing run; never create a database or an owner marker."""
        self.sql_unverified = True
        self.engine = make_engine({**self.settings, 'database': None}, pool_size=1)
        self.conn = self.engine.connect()
        actual = str(self.conn.execute(text('SELECT @@server_uuid')).scalar_one())
        if actual != expected_server:
            raise ValueError('恢复目标 server_uuid 与已记录实例不同')
        self.server_uuid = actual
        ensure_separate_server(self.production_uuid, actual)
        self.locked = self.conn.execute(text('SELECT GET_LOCK(:name,0)'), {'name': self.database}).scalar_one() == 1
        if not self.locked:
            raise RuntimeError('原验证进程或其他恢复仍持有测试库独占锁')
        exists = self.conn.execute(text('SELECT COUNT(*) FROM information_schema.schemata '
                                        'WHERE schema_name=:name'), {'name': self.database}).scalar_one()
        self.created = bool(exists)
        if self.created:
            self.verify_sql_owner()
            self.marked = True
        self.sql_unverified = False

    async def attach_redis(self) -> None:
        self.redis_unverified = True
        self.client = create_client(self.redis)
        actual = await self.client.get(self.owner_key)
        if actual == self.owner:
            self.redis_owned = True
            self.redis_unverified = False
            return
        if actual is not None:
            self.redis_residual = True
            raise ValueError('恢复 Redis owner 不匹配')
        async for _ in self.client.scan_iter(match=self.namespace + ':*', count=100):
            self.redis_residual = True
            raise ValueError('恢复 Redis 有残留但 owner 缺失；拒绝猜测归属')
        self.redis_unverified = False

    def verify_sql_owner(self) -> None:
        rows = self.conn.execute(text(f'SELECT run_id,owner_hash,server_uuid,database_name '
                                      f'FROM `{self.database}`._empire_verifier_owner')).all()
        if [tuple(row) for row in rows] != [(self.run_id, self.owner_hash, self.server_uuid, self.database)]:
            raise ValueError('测试库 owner 不匹配；保留数据库')

    def seed(self, stocks: list[dict], settings: list[dict]) -> None:
        if not self.marked:
            raise ValueError('测试库归属未建立')
        initialize_database(self.settings)
        engine = make_engine(self.settings)
        try:
            with engine.begin() as conn:
                if stocks:
                    conn.execute(text('INSERT INTO stock(unified_code,name) VALUES (:unified_code,:name)'), stocks)
                for row in settings:
                    conn.execute(text('INSERT INTO app_setting(namespace,kind,setting_key,payload) '
                                      'VALUES (:ns,:kind,:key,:payload)'), dict(ns=self.namespace,
                                      kind=row['kind'], key=row['setting_key'],
                                      payload=json.dumps(row['payload'], ensure_ascii=False)))
        finally:
            engine.dispose()

    def cleanup_sql(self) -> None:
        if self.sql_unverified:
            raise ValueError('测试库归属或存在状态尚未证实；保留资源')
        if not self.created:
            return
        if not self.marked or not self.locked or self.conn is None:
            raise ValueError('测试库无完整归属证据；保留数据库')
        server, lock_owner, connection_id = self.conn.execute(text(
            'SELECT @@server_uuid,IS_USED_LOCK(:name),CONNECTION_ID()'), {'name': self.database}).one()
        if server != self.server_uuid or lock_owner != connection_id:
            raise ValueError('测试库实例或独占锁已变化；保留数据库')
        self.verify_sql_owner()
        self.conn.execute(text(f'DROP DATABASE `{self.database}`'))
        remains = self.conn.execute(text('SELECT COUNT(*) FROM information_schema.schemata '
                                         'WHERE schema_name=:name'), {'name': self.database}).scalar_one()
        if remains:
            raise ValueError('测试库删除后仍然存在')
        self.created = False

    async def cleanup_redis(self) -> None:
        if self.redis_unverified:
            raise ValueError('测试 Redis 归属或存在状态尚未证实；保留资源')
        if not self.redis_owned:
            return
        prefix = self.namespace + ':'
        # Producers must have stopped. Scan cycles tolerate Redis SCAN duplicates.
        for _ in range(4):
            found = False
            batch = []
            async for key in self.client.scan_iter(match=prefix + '*', count=100):
                if key == self.owner_key:
                    continue
                found = True
                batch.append(key)
                if len(batch) == 100:
                    await self.client.eval(DELETE_OWNED, len(batch) + 1, self.owner_key,
                                           *batch, self.owner, prefix)
                    batch.clear()
            if batch:
                await self.client.eval(DELETE_OWNED, len(batch) + 1, self.owner_key,
                                       *batch, self.owner, prefix)
            if not found:
                await self.client.eval(DELETE_OWNER, 1, self.owner_key, self.owner)
                async for _ in self.client.scan_iter(match=prefix + '*', count=100):
                    raise ValueError('测试 Redis 清理后仍有键')
                self.redis_owned = False
                self.redis_residual = False
                return
        raise RuntimeError('测试 Redis 清理超过有界扫描次数')

    def release_sql(self) -> None:
        try:
            if self.locked:
                released = self.conn.execute(text('SELECT RELEASE_LOCK(:name)'), {'name': self.database}).scalar_one()
                if released != 1:
                    raise ValueError('测试库独占锁释放失败')
                self.locked = False
        finally:
            if self.conn is not None:
                self.conn.close()
            if self.engine is not None:
                self.engine.dispose()

    def remove_guard(self) -> None:
        if self.guarded:
            event.remove(Engine, 'before_cursor_execute', self.guard)
            self.guarded = False
