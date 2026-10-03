"""One atomic current industry/member set, with no change history."""
import hashlib
import json
import re
from datetime import UTC

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.industries import MEMBER_LIMIT, market, name
from empire.core.time import mysql_time
from empire.plugins.infra.collection_state import confirmed_page

DATASETS = {'industry.snapshot'}
CONTRACT_VERSION = 2
FINGERPRINT_NAMESPACE = 'ths_industries_v2'
FINGERPRINT_VERSION = ArchiveVersion(('utc',), observed_index=0)
PROJECT = 'ths-industries'
JOB = PROJECT + '-v1'
TABLES = {'industry': {'source', 'industry_code', 'name'},
          'industry_member': {'source', 'industry_code', 'market', 'code', 'name'}}
KEYS = {'industry': ['source', 'industry_code'],
        'industry_member': ['source', 'industry_code', 'market', 'code']}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def validate(industries):
    if not isinstance(industries, list) or not 1 <= len(industries) <= 500:
        raise ValueError('行业完整集合无效')
    previous, securities, count = '', set(), 0
    for industry in industries:
        if not isinstance(industry, dict) or set(industry) != {'code', 'name', 'members'}:
            raise ValueError('行业完整集合字段无效')
        code = industry['code']
        if not isinstance(code, str) or not re.fullmatch('[0-9]{6}', code) or code <= previous:
            raise ValueError('行业编号重复或未排序')
        previous = code
        if name(industry['name']) != industry['name']:
            raise ValueError('行业名称未规范化')
        members = industry['members']
        if not isinstance(members, list) or not 1 <= len(members) < MEMBER_LIMIT:
            raise ValueError('行业成分为空或超过上限')
        last = ''
        for member in members:
            if not isinstance(member, list) or len(member) != 2:
                raise ValueError('行业成员结构无效')
            stock, label = member
            market(stock)
            if stock <= last or stock in securities or name(label) != label:
                raise ValueError('行业成员重复、乱序、跨行业冲突或名称无效')
            last = stock
            securities.add(stock)
            count += 1
    if count > 15000:
        raise ValueError('全行业成分超过 15000 条边界')
    return count


def normalize(envelope):
    p = envelope.raw_payload
    if set(p) != {'page', 'industries'} or type(p['page']) is not int or p['page'] != 1:
        raise ValueError('行业快照消息无效')
    count = validate(p['industries'])
    return {**p, 'rows': p['industries'], 'row_count': count}


def canonical_payload(envelope, data):
    return {k: data[k] for k in ('page', 'industries')}


def fingerprint_plan(envelope, data):
    return FINGERPRINT_NAMESPACE, {'current': (data['industries'], [
        envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')])}


def fingerprint_subset(data, identities):
    return data


def read_snapshot(conn, source, *, lock=False):
    params = {'source': source}
    suffix = ' FOR UPDATE' if lock else ''
    rows = conn.execute(text('SELECT industry_code,name FROM industry WHERE source=:source '
                             'ORDER BY industry_code LIMIT 501' + suffix), params).mappings()
    industries = {r['industry_code']: dict(code=r['industry_code'], name=r['name'], members=[])
                  for r in rows}
    members = conn.execute(text('SELECT industry_code,market,code,name FROM industry_member '
        'WHERE source=:source ORDER BY industry_code,code LIMIT 15001' + suffix), params).mappings()
    for row in members:
        if row['industry_code'] not in industries or row['market'] != market(row['code']):
            raise ValueError('行业归档成员关联字段缺失或市场错误')
        industries[row['industry_code']]['members'].append([row['code'], row['name']])
    return list(industries.values())


def write(conn, envelope, data):
    prior = data['archive_state']
    observed = envelope.observed_at.isoformat(timespec='microseconds')
    outcome = dict(status='complete', row_count=data['row_count'], written_count=0, confirmed=[])
    if observed < prior.get('observed_at', ''):
        return outcome
    # Read raw keys here so a new complete source set can repair broken associations.
    params = {'source': envelope.source}
    old_industries = {r['industry_code']: r['name'] for r in conn.execute(text(
        'SELECT industry_code,name FROM industry WHERE source=:source FOR UPDATE'), params).mappings()}
    old_members = {(r['industry_code'], r['market'], r['code']): r['name'] for r in conn.execute(text(
        'SELECT industry_code,market,code,name FROM industry_member WHERE source=:source FOR UPDATE'), params).mappings()}
    industries = {r['code']: r['name'] for r in data['industries']}
    members = {(r['code'], market(m[0]), m[0]): m[1] for r in data['industries'] for m in r['members']}
    for key in old_members.keys() - members.keys():
        conn.execute(text('DELETE FROM industry_member WHERE source=:source AND industry_code=:industry '
                          'AND market=:market AND code=:code'),
                     {**params, 'industry': key[0], 'market': key[1], 'code': key[2]})
        outcome['written_count'] += 1
    for key in old_industries.keys() - industries.keys():
        conn.execute(text('DELETE FROM industry WHERE source=:source AND industry_code=:industry'),
                     {**params, 'industry': key})
        outcome['written_count'] += 1
    for key, label in industries.items():
        if old_industries.get(key) != label:
            conn.execute(text('INSERT INTO industry(source,industry_code,name) VALUES(:source,:industry,:name) '
                'ON DUPLICATE KEY UPDATE name=VALUES(name)'), {**params, 'industry': key, 'name': label})
            outcome['written_count'] += 1
    for key, label in members.items():
        if old_members.get(key) != label:
            conn.execute(text('INSERT INTO industry_member(source,industry_code,market,code,name) '
                'VALUES(:source,:industry,:market,:code,:name) ON DUPLICATE KEY UPDATE name=VALUES(name)'),
                {**params, 'industry': key[0], 'market': key[1], 'code': key[2], 'name': label})
            outcome['written_count'] += 1
    outcome['confirmed'] = ['current']
    return outcome


def archive_state(envelope, data, outcome, previous):
    if not outcome['confirmed']:
        return previous
    publication = previous.get('publication')
    if outcome['written_count'] or not publication:
        publication = dict(batch_id=envelope.batch_id, changed_at=mysql_time(envelope.observed_at).isoformat())
    return dict(contract_version=CONTRACT_VERSION, progress=confirmed_page(envelope, data, previous),
        observed_at=envelope.observed_at.isoformat(timespec='microseconds'), publication=publication,
        digest=digest(data['industries']), industry_count=len(data['industries']), member_count=data['row_count'])
