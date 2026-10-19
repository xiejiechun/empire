"""Independent product/day snapshots, consumed solely by the shared archiver."""
from datetime import UTC, datetime

from empire.contracts.archive_version import ArchiveVersion
from empire.core.time import mysql_time
from empire.features.kaipanla.canonical import identity
from empire.features.kaipanla.contract import project
from empire.features.kaipanla.normalization import business_content, digest, validate
from empire.features.kaipanla.repository import write_day
from empire.plugins.infra.collection_state import confirmed_page


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
