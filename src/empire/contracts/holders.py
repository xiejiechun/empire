"""Typed, bounded report contracts shared by the three holder projects."""
import hashlib
import json
import re
from datetime import date
from decimal import Decimal

KINDS = {'top_holders': ('前十大股东', 'tenholder', 'tdates'),
         'float_holders': ('前十大流通股东', 'flowholder', 'fdates'),
         'bond_holders': ('十大债券持有人', 'bondholder', 'bdates')}
REPORT_FIELDS = ('kind', 'unified_code', 'instrument_key', 'instrument_name', 'report_date', 'report_type',
                 'total_quantity', 'total_quantity_scale', 'total_quantity_decimals', 'total_ratio', 'ratio_basis', 'quality_flags')
MEMBER_FIELDS = ('member_group', 'seq', 'source_rank', 'holder_name', 'holder_id', 'quantity', 'quantity_scale',
                 'quantity_decimals', 'ratio', 'change_quantity', 'change_label', 'actual_change', 'share_type',
                 'pledge_ratio', 'pledge_status')

QUALITY = {1: '当期持有比例未知', 2: '前十大数量合计与来源汇总不符',
           4: '前十大比例合计与来源汇总不符', 8: '来源数量汇总未知', 16: '来源比例汇总未知',
           32: '当期持有数量未知', 64: '退出持有数量未知', 128: '来源报告期晚于采集观察日'}


def quality_details(report, *, today=None):
    """Compare source values without replacing them or certifying a missing row."""
    current = [m for m in report['members'] if m['member_group'] == 'current']
    issues = []
    for group, flag in (('current', 32), ('exited', 64)):
        unknown_quantity = sum(m['quantity'] is None for m in report['members'] if m['member_group'] == group)
        if unknown_quantity:
            issues.append(dict(flag=flag, reason=QUALITY[flag], unknown_members=unknown_quantity,
                               detail=f'{unknown_quantity}位持有人数量未知；未以零或比例推算'))
    # Without an observation date this is a stored source fact, authenticated by
    # the report hash. Ingest always rechecks it against the envelope observation.
    if (date.fromisoformat(report['report_date']) > today if today is not None else
            report.get('quality_flags', 0) & 128):
        issues.append(dict(flag=128, reason=QUALITY[128], detail='保留来源报告期；不得提前作为历史信号'))
    unknown = sum(m['ratio'] is None for m in current)
    if unknown:
        issues.append(dict(flag=1, reason=QUALITY[1], unknown_members=unknown))
    if report['report_type'] == 'change_notice':
        return issues
    for field, flag, missing in (('quantity', 2, 8), ('ratio', 4, 16)):
        total = report['total_' + field]
        known = sum((Decimal(m[field]) for m in current if m[field] is not None), Decimal(0))
        if total is None:
            issues.append(dict(flag=missing, reason=QUALITY[missing], source=None, known_sum=str(known)))
            continue
        unknown_field = any(m[field] is None for m in current)
        tolerance = Decimal('.15')
        if field == 'quantity':
            tolerance = sum(Decimal(m['quantity_scale']) * Decimal(10)**(-m['quantity_decimals']) / 2
                            for m in current if m['quantity'] is not None)
            tolerance += Decimal(report['total_quantity_scale']) * Decimal(10)**(-report['total_quantity_decimals']) / 2
        delta = known - Decimal(total)
        # Unknown ratios cannot prove equality; known values can prove overflow.
        mismatch = delta > tolerance if unknown_field else abs(delta) > tolerance
        if mismatch:
            issues.append(dict(flag=flag, reason=QUALITY[flag], source=total,
                               known_sum=str(known), difference=str(delta), tolerance=str(tolerance)))
    return issues


def quality_flags(report, *, today=None):
    return sum(issue['flag'] for issue in quality_details(report, today=today))


def project(kind):
    if kind not in KINDS:
        raise ValueError('未知持有人栏目')
    return 'ths-holders'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def number(value, *, ratio=False, signed=False, total=False):
    if not isinstance(value, str) or not re.fullmatch(r'-?\d+(?:\.\d{1,4})?', value):
        raise ValueError('持有人数值格式或精度无效')
    parsed = Decimal(value)
    if (not signed and parsed < 0) or abs(parsed) >= (Decimal('100.1501') if total else Decimal('100.0001') if ratio else Decimal(10)**20):
        raise ValueError('持有人数值超出范围')
    return format(parsed.normalize(), 'f')


def quantity(text, *, scale=1, unit=None):
    match = re.fullmatch(r'(-?\d+(?:\.\d{1,4})?)(万|亿)?(股|张)?', text.replace(',', ''))
    if not match:
        raise ValueError('持有数量或单位无效：' + text[:80])
    if unit and match[3] and match[3] != unit:
        raise ValueError('持有数量单位与业务类型不符')
    factor = {'万': 10000, '亿': 100000000}.get(match[2], 1 if match[3] else scale)
    value = number(format(Decimal(match[1]) * factor, 'f'), signed=True)
    return value, factor, len(match[1].partition('.')[2])


def report_key(report):
    return digest([report[k] for k in ('kind', 'unified_code', 'instrument_key', 'report_date', 'report_type')])


def validate_gaps(gaps):
    if not isinstance(gaps, list) or len(gaps) > 100:
        raise ValueError('持有人来源缺口数量无效')
    identities = set()
    for gap in gaps:
        if (not isinstance(gap, dict) or set(gap) != {'kind', 'report_date', 'source_panel', 'reason'} or
                gap['kind'] != 'bond_holders' or gap['reason'] != 'instrument_name_missing' or
                not isinstance(gap['source_panel'], str) or not 1 <= len(gap['source_panel']) <= 100 or
                not isinstance(gap['report_date'], str) or
                date.fromisoformat(gap['report_date']).isoformat() != gap['report_date']):
            raise ValueError('持有人来源缺口字段无效')
        identity = (gap['kind'], gap['source_panel'])
        if identity in identities:
            raise ValueError('持有人来源缺口定位重复')
        identities.add(identity)
    return gaps


def validate(kind, security, reports, *, today=None, allow_unidentified=False):
    if kind not in KINDS or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', security):
        raise ValueError('持有人项目或证券身份无效')
    if not isinstance(reports, list) or len(reports) > 100:
        raise ValueError('持有人报告窗口超限')
    keys = set()
    for r in reports:
        if set(r) != {*REPORT_FIELDS, 'members'} or r['kind'] != kind or r['unified_code'] != security:
            raise ValueError('持有人报告字段或归属无效')
        stamp = date.fromisoformat(r['report_date'])
        if stamp.isoformat() != r['report_date']:
            raise ValueError('持有人报告日期无效')
        name = r['instrument_name']
        missing_bond = allow_unidentified and kind == 'bond_holders' and name == ''
        if not isinstance(name, str) or (not missing_bond and not 1 <= len(name) <= 200) or r['instrument_key'] != digest(name):
            raise ValueError('持有人标的身份无效')
        if kind != 'bond_holders' and name != security:
            raise ValueError('股票持有人报告标的与证券不符')
        key = report_key(r)
        if key in keys:
            raise ValueError('重复的持有人报告')
        keys.add(key)
        if r['report_type'] not in ('periodic', 'change_notice') or kind == 'bond_holders' and r['report_type'] != 'periodic':
            raise ValueError('持有人报告类型无效')
        for prefix in ('total_quantity',):
            if r['report_type'] == 'change_notice':
                if any(r[prefix + suffix] is not None for suffix in ('', '_scale', '_decimals')):
                    raise ValueError('变动公告不得伪造前十大汇总')
                continue
            if r[prefix] is None:
                if any(r[prefix + suffix] is not None for suffix in ('_scale', '_decimals')):
                    raise ValueError('未知来源汇总不得伪造精度')
                continue
            number(r[prefix])
            if type(r[prefix + '_scale']) is not int or r[prefix + '_scale'] not in (1, 10000, 100000000) or type(r[prefix + '_decimals']) is not int or not 0 <= r[prefix + '_decimals'] <= 4:
                raise ValueError('来源显示精度无效')
        if r['report_type'] == 'periodic' and r['total_ratio'] is not None:
            number(r['total_ratio'], ratio=True, total=True)
        elif r['report_type'] == 'change_notice' and r['total_ratio'] is not None:
            raise ValueError('变动公告不得伪造前十大比例')
        if not isinstance(r['ratio_basis'], str) or not 1 <= len(r['ratio_basis']) <= 64:
            raise ValueError('持有人比例口径无效')
        groups = {'current': [], 'exited': []}
        identities, names = set(), set()
        if not isinstance(r['members'], list) or len(r['members']) > 400:
            raise ValueError('持有人明细超限')
        for member in r['members']:
            if set(member) != set(MEMBER_FIELDS) or member['member_group'] not in groups:
                raise ValueError('持有人明细字段无效')
            group = member['member_group']
            groups[group].append(member['seq'])
            for field, limit, required in (('holder_name', 512, True), ('holder_id', 80, False),
                    ('change_label', 16, False), ('actual_change', 128, False), ('share_type', 128, False),
                    ('pledge_status', 64, False)):
                value = member[field]
                if value is None and not required:
                    continue
                if not isinstance(value, str) or not 1 <= len(value) <= limit:
                    raise ValueError('持有人文本缺失或超限：' + field)
            identity = (group, member['holder_id'] or member['holder_name'], member['share_type'])
            name_key = (group, member['holder_name'], member['share_type'])
            if identity in identities or name_key in names:
                raise ValueError('同条数不同集合：重复持有人身份')
            identities.add(identity)
            names.add(name_key)
            if member['quantity'] is not None:
                number(member['quantity'])
            elif member['quantity_scale'] is not None or member['quantity_decimals'] is not None:
                raise ValueError('未知持有数量不得伪造精度')
            if member['ratio'] is not None:
                number(member['ratio'], ratio=True)
            rank = member['source_rank']
            if kind == 'bond_holders':
                if type(rank) is not int or not 1 <= rank <= 9999:
                    raise ValueError('债券来源排名无效')
            elif rank is not None:
                raise ValueError('股票名单不得伪造来源排名')
            if member['pledge_ratio'] is not None:
                number(member['pledge_ratio'], ratio=True)
            if member['change_quantity'] is not None:
                number(member['change_quantity'], signed=True)
            if member['quantity'] is not None and (type(member['quantity_scale']) is not int or member['quantity_scale'] not in (1, 10000, 100000000) or type(member['quantity_decimals']) is not int or not 0 <= member['quantity_decimals'] <= 4):
                raise ValueError('明细显示精度无效')
        current_limit = 10 if kind == 'bond_holders' else 200
        if not 1 <= len(groups['current']) <= current_limit or len(groups['exited']) > 200:
            raise ValueError('前十大名单数量无效')
        for sequences in groups.values():
            if sequences != list(range(1, len(sequences) + 1)):
                raise ValueError('持有人规范行序号无效')
        ranks = [m['source_rank'] for m in r['members'] if m['member_group'] == 'current']
        if kind == 'bond_holders' and ranks != sorted(ranks):
            raise ValueError('债券来源排名顺序无效')
        if r['members'] != sorted(r['members'], key=lambda m: (m['member_group'], m['seq'])):
            raise ValueError('持有人分组及序号未按规范排序')
        current = [m for m in r['members'] if m['member_group'] == 'current']
        # The stock page can publish more than ten distinct members even
        # without a tenth-place tie (000430, 2026-03-31). Its caption totals
        # describe the whole current body, not an inferred top-ten subset.
        # Preserve that bounded source set and verify both independent totals.
        if r['total_ratio'] is not None and Decimal(r['total_ratio']) > Decimal(100) + Decimal(len(current)) * Decimal('.005'):
            raise ValueError('持有人汇总比例超出成员舍入上界')
        issues = quality_details(r, today=today)
        expected = sum(issue['flag'] for issue in issues)
        if type(r['quality_flags']) is not int or r['quality_flags'] != expected:
            raise ValueError((issues[0]['reason'] if issues else '持有人来源质量标记无效') + '；质量标记与来源原值不符')
    return reports
