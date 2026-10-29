"""Complete date pools and independent reasons on unified archive contracts."""
from datetime import UTC, time

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.core.time import CHINA, mysql_time
from empire.features.yuanhang_limits.contract import SOURCE, dataset, job, project
from empire.features.yuanhang_limits.repository import (
    read_pool_head,
    read_reason,
    replace_pool,
    replace_reason,
)
from empire.features.yuanhang_limits.storage import pool_payload, reason_payload
from empire.features.yuanhang_limits.wire import decode, encode
from empire.plugins.infra.collection_state import confirmed_page


class LimitDataset:
    FINGERPRINT_VERSION = ArchiveVersion(('utc',), observed_index=0)

    def __init__(self, pool):
        self.pool = pool
        self.DATASETS, self.PROJECT, self.JOB = {dataset(pool)}, project(pool), job(pool)
        self.FINGERPRINT_NAMESPACE = 'yuanhang_limits_' + pool + '_v1'

    def normalize(self, envelope):
        p = envelope.raw_payload
        if (envelope.source != SOURCE or set(p) != {'page', 'unit_zlib'}
                or type(p['page']) is not int or not 1 <= p['page'] <= 10000000):
            raise ValueError('涨停分析入队身份或批次页序无效')
        unit = (reason_payload if self.pool == 'reason' else pool_payload)(decode(p['unit_zlib']))
        observed = envelope.observed_at.astimezone(CHINA)
        if (unit['trade_date'] > observed.date().isoformat() or
                unit['trade_date'] == observed.date().isoformat() and observed.time().replace(tzinfo=None) < time(15, 30)):
            raise ValueError('未完成交易日的盘中快照不得进入MySQL归档')
        if self.pool != 'reason' and unit['pool_type'] != self.pool:
            raise ValueError('日期池贡献归属不符')
        identity = unit['trade_date'] + (':' + unit['unified_code'] if self.pool == 'reason' else ':' + self.pool)
        if envelope.business_key != identity:
            raise ValueError('涨停分析消息业务键不符')
        return dict(page=p['page'], unit=unit, identity=identity,
                    row_count=1 if self.pool == 'reason' else len(unit['rows']))

    def canonical_payload(self, envelope, data):
        return {'page': data['page'], 'unit_zlib': encode(data['unit'])}

    def state_unit(self, data):
        return data['unit']['unified_code'] if self.pool == 'reason' else None

    def fingerprint_plan(self, envelope, data):
        return self.FINGERPRINT_NAMESPACE, {data['identity']: (data['unit'],
            [envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')])}

    def fingerprint_subset(self, data, identities):
        return {**data, 'write_unit': data['identity'] in identities}

    def versions(self, state, unit):
        state = state.get('units', {}).get(unit['unified_code'], {}) if self.pool == 'reason' else state
        return state.get('versions', {})

    def write(self, conn, envelope, data):
        tables = ('yuanhang_limit_reason',) if self.pool == 'reason' else ('yuanhang_limit_pool', 'yuanhang_limit_member')
        for table in tables:
            require_fixed_source(table, envelope.source)
        unit = data['unit']
        observed = envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')
        previous = self.versions(data['archive_state'], unit).get(unit['trade_date'], '')
        outcome = dict(status='complete', row_count=data['row_count'], written_count=0, confirmed=[])
        if not data.get('write_unit', True) or observed < previous:
            return outcome
        if self.pool == 'reason':
            head = read_reason(conn, unit['trade_date'], unit['unified_code'], lock=True)
        else:
            head = read_pool_head(conn, unit['trade_date'], self.pool, lock=True)
        if head and mysql_time(envelope.observed_at) < head['observed_at']:
            return outcome
        writer = replace_reason if self.pool == 'reason' else replace_pool
        outcome.update(written_count=writer(conn, unit, envelope.observed_at, head), confirmed=[data['identity']])
        return outcome

    def archive_state(self, envelope, data, outcome, previous):
        if not outcome['confirmed']:
            return previous
        unit = data['unit']
        versions = {**self.versions(previous, unit),
                    unit['trade_date']: envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')}
        if len(versions) > 36600:
            raise ValueError('涨停分析日期版本索引超过100年上限')
        state = dict(contract_version=1, progress=confirmed_page(envelope, data, previous))
        if self.pool == 'reason':
            state['units'] = {unit['unified_code']: {'versions': versions}}
        else:
            state['versions'] = versions
        return state
