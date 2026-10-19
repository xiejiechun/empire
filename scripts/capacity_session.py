"""Owned SQL capacity runs: measured identity, independent cleanup, durable result."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import event, text

from empire.plugins.infra.mysql_store import make_engine


def server_uuid(value):
    if not isinstance(value, str) or not re.fullmatch(
            '[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', value):
        raise ValueError('MySQL server_uuid 缺失或格式无效')
    return value.lower()


def require_sample_kinds(samples, expected):
    actual = [row['kind'] for row, _observed in samples]
    missing = sorted(set(expected) - set(actual))
    if missing or len(actual) != len(expected) or set(actual) != set(expected):
        raise ValueError('声明的容量样本未验收；缺少种类：' + ','.join(missing)
                         + ('；样本重复或包含额外种类' if len(actual) != len(set(actual)) or set(actual) - set(expected) else ''))


class CapacitySession:
    """One synchronous SQL owner; never changes service or production settings.

    This is an execution harness, not a general SQL grammar validator. All
    measurement writers receive only ``engine`` / ``settings`` for the owned
    database. The source engine is used by preview's explicit read-only snapshot.
    """

    def __init__(self, production, test, *, root, subject, output=None, input_paths=()):
        if subject not in {'holders', 'ths-capital', 'preview'}:
            raise ValueError('Unknown capacity subject')
        self.root = Path(root)
        self.run_id = uuid4().hex
        self.database = 'empire_capacity_' + self.run_id + '_test'
        self.production = dict(production)
        self.settings = {**test, 'database': self.database}
        self.output = Path(output) if output else self.root / 'build' / 'capacity-reruns' / (subject + '-' + self.run_id + '.json')
        if self.output.exists():
            raise FileExistsError('容量报告必须使用新路径，不能覆盖已有证据')
        self.report = dict(run_id=self.run_id, subject=subject,
                           started_at=datetime.now(UTC).isoformat(), passed=False,
                           measurements_complete=False, errors=[], cleanup={})
        self.engine = self.admin = self.admin_conn = self.source_engine = None
        self.identity = {}
        self.production_uuid = ''
        self.created = self.creation_attempted = self.locked = False
        self.measurements_complete = False
        self.input_paths = tuple(input_paths)
        self.frozen_inputs = None

    def input_identity(self):
        result = {}
        for name in self.input_paths:
            path = self.root / name
            if not path.resolve().is_relative_to(self.root.resolve()) or not path.is_file():
                raise ValueError('容量输入必须是项目内现有文件')
            result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result

    def __enter__(self):
        try:
            self.frozen_inputs = self.input_identity()
            self.source_engine = make_engine(self.production)
            with self.source_engine.connect() as conn:
                self.production_uuid = server_uuid(conn.exec_driver_sql('SELECT @@server_uuid').scalar_one())
            self.admin = make_engine({**self.settings, 'database': None}, pool_size=1)
            self.admin_conn = self.admin.connect()
            self.identity = dict(self.admin_conn.exec_driver_sql(
                'SELECT @@server_uuid AS server_uuid,@@port AS server_port,VERSION() AS version,'
                '@@innodb_flush_log_at_trx_commit AS innodb_flush_log_at_trx_commit,'
                '@@sync_binlog AS sync_binlog,@@log_bin AS log_bin').mappings().one())
            test_uuid = server_uuid(self.identity['server_uuid'])
            self.identity['server_uuid'] = test_uuid
            if test_uuid == self.production_uuid:
                raise ValueError('容量测量必须使用不同 server_uuid 的独立 MySQL 服务')
            self.identity['client_port'] = int(self.settings.get('port', 3306))
            self.locked = self.admin_conn.execute(text('SELECT GET_LOCK(:name,0)'),
                                                   {'name': self.database}).scalar_one() == 1
            if not self.locked:
                raise RuntimeError('容量私有库独占锁不可用')
            self.creation_attempted = True
            self.admin_conn.exec_driver_sql(f'CREATE DATABASE `{self.database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin')
            self.created = True
            self.engine = make_engine(self.settings)
            event.listen(self.engine, 'checkout', self.check_connection)
            return self
        except BaseException as exc:
            self.finish(exc)
            raise

    def check_connection(self, connection, _record, _proxy):
        cursor = connection.cursor()
        try:
            cursor.execute('SELECT @@server_uuid,DATABASE()')
            server, database = cursor.fetchone()
            if (server_uuid(server), database) != (self.identity['server_uuid'], self.database):
                raise ValueError('容量业务连接实际实例或数据库变化')
        finally:
            cursor.close()

    def require_source(self, conn):
        if server_uuid(conn.exec_driver_sql('SELECT @@server_uuid').scalar_one()) != self.production_uuid:
            raise ValueError('容量只读来源实际 MySQL 实例变化')

    def drop_database(self):
        if not self.created:
            if self.creation_attempted:
                raise RuntimeError('CREATE 未确认；保留未核实私有库供人工精确恢复')
            return
        if not re.fullmatch('empire_capacity_[0-9a-f]{32}_test', self.database):
            raise ValueError('容量私有库名称无效')
        self.admin_conn.rollback()
        server, owner, connection = self.admin_conn.execute(text(
            'SELECT @@server_uuid,IS_USED_LOCK(:name),CONNECTION_ID()'),
            {'name': self.database}).one()
        if server_uuid(server) != self.identity['server_uuid'] or server_uuid(server) == self.production_uuid or owner != connection:
            raise ValueError('容量清理无法确认独立实例与本轮锁归属')
        self.admin_conn.exec_driver_sql(f'DROP DATABASE `{self.database}`')
        remaining = self.admin_conn.execute(text(
            'SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name=:name'),
            {'name': self.database}).scalar_one()
        if remaining:
            raise RuntimeError('容量私有库清理后仍存在')
        self.created = False

    def release_lock(self):
        if self.locked:
            released = self.admin_conn.execute(text('SELECT RELEASE_LOCK(:name)'),
                                                {'name': self.database}).scalar_one()
            if released != 1:
                raise RuntimeError('容量私有库锁释放未确认')
            self.locked = False

    def cleanup(self):
        failures = []
        operations = [
            ('business_engine', self.engine.dispose if self.engine is not None else None),
            ('sql', self.drop_database),
            ('sql_lock', self.release_lock),
            ('admin_connection', self.admin_conn.close if self.admin_conn is not None else None),
            ('admin_engine', self.admin.dispose if self.admin is not None else None),
            ('source_engine', self.source_engine.dispose if self.source_engine is not None else None),
        ]
        for stage, operation in operations:
            try:
                if operation is not None:
                    operation()
                self.report['cleanup'][stage] = True
            except BaseException as exc:
                self.report['cleanup'][stage] = False
                self.report['errors'].append({'stage': stage, 'type': type(exc).__name__})
                failures.append(exc)
        return failures

    def write_report(self):
        self.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.output.with_name('.' + self.output.name + '.' + self.run_id + '.tmp')
        published = False
        try:
            with temporary.open('x', encoding='utf-8') as stream:
                json.dump(self.report, stream, ensure_ascii=False, indent=2, default=str)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            # Same-directory hard-link publication is atomic and fails if a
            # concurrent owner created the destination. Never replace evidence.
            os.link(temporary, self.output)
            published = True
            temporary.unlink()
        except BaseException as primary:
            try:
                if published and temporary.exists() and self.output.exists() and os.path.samefile(temporary, self.output):
                    self.output.unlink()
                temporary.unlink(missing_ok=True)
            except BaseException as cleanup_error:
                primary.add_note('Report temporary cleanup failure: ' + type(cleanup_error).__name__)
            raise

    def finish(self, primary):
        if primary is not None:
            # Exception objects remain on the original traceback. Reports store
            # types only, never SQL parameters, credentials or driver messages.
            self.report['errors'].append({'stage': 'measurement', 'type': type(primary).__name__})
        failures = self.cleanup()
        if self.frozen_inputs is not None:
            try:
                if self.input_identity() != self.frozen_inputs:
                    raise ValueError('容量测量或清理期间输入发生变化')
                if self.input_paths and self.report.get('bindings') != self.frozen_inputs:
                    raise ValueError('容量报告绑定与测量前输入不一致')
                self.report['input_identity_verified'] = True
            except BaseException as exc:
                failures.append(exc)
                self.report['input_identity_verified'] = False
                self.report['errors'].append({'stage': 'input_identity', 'type': type(exc).__name__})
        if primary is None and not self.measurements_complete:
            failures.append(RuntimeError('容量测量未明确完成'))
            self.report['errors'].append({'stage': 'measurement', 'type': 'IncompleteMeasurement'})
        self.report.update(checked_at=datetime.now(UTC).isoformat(),
                           measurements_complete=self.measurements_complete,
                           database=self.database, measurement_service=self.identity,
                           passed=primary is None and not failures and self.measurements_complete)
        try:
            self.write_report()
        except BaseException as exc:
            self.report['passed'] = False
            self.report['errors'].append({'stage': 'report', 'type': type(exc).__name__})
            failures.append(exc)
        if primary is not None:
            for failure in failures:
                primary.add_note('Capacity cleanup/report failure: ' + type(failure).__name__)
            return
        if failures:
            raise BaseExceptionGroup('Capacity cleanup/report failed; no PASS', failures)

    def __exit__(self, _kind, primary, _traceback):
        self.finish(primary)
        return False
