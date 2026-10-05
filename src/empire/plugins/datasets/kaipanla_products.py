"""Independent product/day snapshots, consumed solely by the shared archiver."""
from datetime import UTC, date, datetime

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.security import unified_code
from empire.core.time import CHINA, mysql_time
from empire.plugins.collectors.kaipanla_kinds import PRODUCTS, project
from empire.plugins.collectors.kaipanla_products_source import parse
from empire.plugins.datasets.intraday import digest as hash_value
from empire.plugins.datasets.intraday import identity
from empire.plugins.datasets.market_repository import write_day
from empire.plugins.infra.collection_state import confirmed_page
from empire.plugins.infra.schema_manifest import market_contract

TABLES, KEYS = market_contract()
FIELDS = {'kind', 'code', 'market', 'trade_date', 'source_code', 'aliases', 'data', 'lifecycle', 'metadata'}


def business_content(row):
    # Source calculation/observation clocks have no proven revision semantics.
    # They remain available as metadata, without causing repeated business DML.
    return {k: v for k, v in row.items() if k != 'metadata'}


def digest(row):
    return hash_value(business_content(row))


def validate(row, kind=None, *, storage_check=True):
    if not isinstance(row, dict) or set(row) != FIELDS:
        raise ValueError('证券日字段不完整')
    item = PRODUCTS.get(row['kind'])
    if item is None or kind is not None and kind != row['kind']:
        raise ValueError('证券日数据类型错配')
    unified_code(row['market'], row['code'])
    day = date.fromisoformat(row['trade_date'])
    if day.isoformat() != row['trade_date'] or not date(2021, 1, 1) <= day <= datetime.now(CHINA).date():
        raise ValueError('日期超出支持范围')
    life = row['lifecycle']
    if (not isinstance(life, dict) or set(life) != {'listing_date', 'listing_source', 'market_start'}
            or life['listing_source'] != 'eastmoney'
            or day < max(date.fromisoformat(life['listing_date']), date.fromisoformat(life['market_start']))):
        raise ValueError('上市生命周期无效')
    if not isinstance(row['data'], dict) or not isinstance(row['aliases'], dict):
        raise ValueError('业务内容或映射证明无效')
    expected_alias = {row['source_code']} - {row['code'], None}
    if set(row['aliases']) != expected_alias:
        raise ValueError('来源代码映射关联错误')
    for proof in row['aliases'].values():
        if row['market'] != 'BJ' or proof['listing_date'] != life['listing_date']:
            raise ValueError('旧代码市场或上市日期错配')
    if not isinstance(row['metadata'], dict) or set(row['metadata']) - {'time', 'time2', 'ts'}:
        raise ValueError('来源元数据无效')
    payload = {**row['data'], **row['metadata'], 'errcode': '0', 'day': day.strftime('%Y%m%d')}
    if row['source_code'] is not None:
        payload['code'] = row['source_code']
    parsed = parse(payload, row['code'], day, row['kind'], row['aliases'])
    if parsed['data'] != row['data']:
        raise ValueError('业务数据未按现行契约规范化')
    from empire.plugins.datasets.market_mapping import encode
    if storage_check:
        encode(row, '', datetime.now(CHINA).replace(tzinfo=None))
    return row


def point_count(row):
    field = PRODUCTS[row['kind']].field
    return len(row['data'][field]) if field else 1


class ProductDataset:
    FINGERPRINT_VERSION = ArchiveVersion(('utc',), observed_index=0)

    def __init__(self, kind):
        self.kind = kind
        self.PROJECT = project(kind)
        self.JOB = self.PROJECT + '-v1'
        self.DATASETS = {'kaipanla.' + kind + '.day'}
        self.FINGERPRINT_NAMESPACE = 'kaipanla_' + kind + '_v1'

    def normalize(self, envelope):
        payload = envelope.raw_payload
        if set(payload) != {'page', 'rows'} or type(payload['page']) is not int or payload['page'] < 1:
            raise ValueError('证券日消息分页无效')
        rows = payload['rows']
        if not isinstance(rows, list) or len(rows) != 1:
            raise ValueError('必须发布一个完整证券日')
        validate(rows[0], self.kind)
        if envelope.business_key != identity(rows[0]):
            raise ValueError('消息证券日期错配')
        return dict(page=payload['page'], rows=rows, row_count=1)

    def canonical_payload(self, envelope, data):
        return dict(page=data['page'], rows=data['rows'])

    def fingerprint_plan(self, envelope, data):
        version = [envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')]
        return self.FINGERPRINT_NAMESPACE, {identity(r): (business_content(r), version) for r in data['rows']}

    def fingerprint_subset(self, data, identities):
        return {**data, 'rows': [r for r in data['rows'] if identity(r) in identities]}

    def write(self, conn, envelope, data):
        if envelope.source != 'kaipanla':
            raise ValueError('固定来源错配')
        confirmed, writes = [], 0
        observed = mysql_time(envelope.observed_at)
        for row in data['rows']:
            previous = data.get('archive_state', {})
            progress = previous.get('progress', {})
            if (previous.get('last_security_day') == identity(row) and progress.get('observed_at')
                    and envelope.observed_at < datetime.fromisoformat(progress['observed_at'])):
                continue
            accepted, changed = write_day(conn, row, digest(row), observed)
            writes += changed
            if accepted:
                confirmed.append(identity(row))
        return dict(status='complete', row_count=len(data['rows']), written_count=writes, confirmed=confirmed)

    def archive_state(self, envelope, data, outcome, previous):
        if not outcome['confirmed']:
            return previous
        return dict(contract_version=1, progress=confirmed_page(envelope, data, previous),
                    last_security_day=identity(data['rows'][0]))
