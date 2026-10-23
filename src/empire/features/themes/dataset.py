"""Theme units on the shared fingerprint, state, transaction and queue pathway."""
from datetime import UTC, date

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.core.time import CHINA
from empire.features.themes.history_model import digest
from empire.features.themes.repository import (
    read_daily,
    read_detail_head,
    replace_daily,
    replace_detail,
)
from empire.features.themes.storage_contract import (
    DETAIL_DATASET,
    DETAIL_JOB,
    DETAIL_PROJECT,
    LIST_DATASET,
    LIST_JOB,
    LIST_PROJECT,
    detail_version,
    epoch,
    list_rows,
    validate_detail,
)
from empire.plugins.infra.collection_state import confirmed_page


class ThemeDailyDataset:
    DATASETS, PROJECT, JOB = {LIST_DATASET}, LIST_PROJECT, LIST_JOB
    FINGERPRINT_NAMESPACE = 'kaipanla_themes_daily_v1'
    FINGERPRINT_VERSION = ArchiveVersion(('utc',), observed_index=0)

    def normalize(self, envelope):
        value = envelope.raw_payload
        if (not isinstance(value, dict) or set(value) != {'page', 'day', 'rows'}
                or type(value['page']) is not int or value['page'] != 1
                or not isinstance(value['day'], str)
                or date.fromisoformat(value['day']).isoformat() != value['day']
                or value['day'] != envelope.observed_at.astimezone(CHINA).date().isoformat()
                or envelope.business_key != value['day']):
            raise ValueError('每日题材消息身份或日期无效')
        rows = list_rows(value['rows'])
        return {**value, 'rows': rows, 'row_count': len(rows)}

    def canonical_payload(self, envelope, data):
        return {k: data[k] for k in ('page', 'day', 'rows')}

    def fingerprint_plan(self, envelope, data):
        version = [envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')]
        return self.FINGERPRINT_NAMESPACE, {data['day']: (data['rows'], version)}

    def fingerprint_subset(self, data, identities):
        return data

    def write(self, conn, envelope, data):
        require_fixed_source('theme_daily', envelope.source)
        _, plan = self.fingerprint_plan(envelope, data)
        incoming = plan[data['day']][1]
        previous = data['archive_state'].get('latest', {})
        outcome = dict(status='complete', row_count=len(data['rows']), written_count=0, confirmed=[])
        # One latest proof is enough: this collector never backfills historical days.
        if previous.get('version') and self.FINGERPRINT_VERSION.compare(incoming, previous['version']) < 0:
            return outcome
        records, _ = read_daily(conn, data['day'], lock=True)
        if any(mysql_observed(r['observed_at']) > incoming[0] for r in records):
            raise ValueError('每日题材业务版本超过统一状态，拒绝覆盖')
        outcome['written_count'] = replace_daily(conn, data['day'], data['rows'], envelope.observed_at)
        outcome['confirmed'] = [data['day']]
        return outcome

    def archive_state(self, envelope, data, outcome, previous):
        if not outcome['confirmed']:
            return previous
        _, plan = self.fingerprint_plan(envelope, data)
        return {'contract_version': 1, 'progress': confirmed_page(envelope, data, previous),
                'latest': {'day': data['day'], 'version': plan[data['day']][1],
                           'count': len(data['rows']), 'digest': digest(data['rows'])}}


def mysql_observed(value):
    return value.replace(tzinfo=CHINA).astimezone(UTC).isoformat(timespec='microseconds')


class ThemeDetailDataset:
    DATASETS, PROJECT, JOB = {DETAIL_DATASET}, DETAIL_PROJECT, DETAIL_JOB
    FINGERPRINT_NAMESPACE = 'kaipanla_themes_detail_v1'
    FINGERPRINT_VERSION = ArchiveVersion(('utc', 'utc'), observed_index=1, source_indices=(0,))

    def normalize(self, envelope):
        value = envelope.raw_payload
        if (not isinstance(value, dict) or set(value) != {'page', 'detail'}
                or type(value['page']) is not int or not 1 <= value['page'] <= 2000):
            raise ValueError('题材详情消息字段无效')
        detail = validate_detail(value['detail'])
        if detail['theme_id'] != envelope.business_key:
            raise ValueError('题材详情消息身份不符')
        detail = {**detail, 'stocks': sorted(detail['stocks'], key=lambda r: r['source_stock_id']),
                  'relations': sorted(detail['relations'], key=lambda r: r['relation_id'])}
        return {**value, 'detail': detail, 'row_count': len(detail['relations'])}

    def canonical_payload(self, envelope, data):
        return {k: data[k] for k in ('page', 'detail')}

    def fingerprint_plan(self, envelope, data):
        value = data['detail']
        return self.FINGERPRINT_NAMESPACE, {value['theme_id']: (value, detail_version(value, envelope.observed_at))}

    def fingerprint_subset(self, data, identities):
        return data

    def write(self, conn, envelope, data):
        for table in ('theme_detail', 'theme_category', 'theme_stock', 'theme_stock_reason'):
            require_fixed_source(table, envelope.source)
        detail = data['detail']
        incoming = detail_version(detail, envelope.observed_at)
        prior = data['archive_state'].get('units', {}).get(detail['theme_id'], {})
        outcome = dict(status='complete', row_count=data['row_count'], written_count=0, confirmed=[])
        if prior.get('version') and self.FINGERPRINT_VERSION.compare(incoming, prior['version']) < 0:
            return outcome
        head = read_detail_head(conn, detail['theme_id'], lock=True)
        if head:
            version = detail_version({'source_updated_at': epoch(head['source_updated_at'])},
                                     head['observed_at'].replace(tzinfo=CHINA))
            if self.FINGERPRINT_VERSION.compare(incoming, version) < 0:
                return outcome
        outcome['written_count'] = replace_detail(conn, detail, envelope.observed_at)
        outcome['confirmed'] = [detail['theme_id']]
        return outcome

    def archive_state(self, envelope, data, outcome, previous):
        if not outcome['confirmed']:
            return previous
        detail = data['detail']
        units = {**previous.get('units', {}), detail['theme_id']: {
            'version': detail_version(detail, envelope.observed_at), 'digest': digest(detail),
            'stocks': len(detail['stocks']), 'relations': sum(r['occurrences'] for r in detail['relations'])}}
        if len(units) > 2000:
            raise ValueError('题材详情确认状态超限，须显式维护')
        return {'contract_version': 1, 'progress': confirmed_page(envelope, data, previous), 'units': units}
