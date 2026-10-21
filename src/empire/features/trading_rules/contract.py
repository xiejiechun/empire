"""Typed, bounded trading parameters and shared clause citations."""
import hashlib
import json
import re
from datetime import date, time
from decimal import Decimal
from urllib.parse import urlsplit

from empire.features.trading_rules.review import EXPECTED, REFERENCES

KINDS = {
    'limit_rules': '涨跌幅规则记录', 'settlement_rules': '买入后何时能卖的规则',
    'lot_rules': '最小买卖数量规则', 'tick_rules': '最小价格变动规则',
    'sessions': '交易时段规则', 'stamp_duty': '印花税税率记录', 'transfer_fee': '过户费收费记录',
}
SOURCE = 'reviewed_rules'
VERSION = 1
VALUE_COLUMNS = ('kind', 'market', 'board', 'condition_key', 'parameter_key', 'effective_start',
                 'effective_end', 'number_value', 'text_value', 'start_time', 'end_time', 'unit', 'citation_key')
CITATION_COLUMNS = ('issuer', 'title', 'source_url', 'published_date', 'document_hash', 'clause_key', 'excerpt')
PARAMETERS = {
    'limit_rules': {'limit_ratio', 'exemptions', 'rounding'},
    'settlement_rules': {'resale_constraint'},
    'lot_rules': {'buy_minimum', 'buy_increment', 'odd_lot', 'star_orders', 'maximum'},
    'tick_rules': {'price_tick'}, 'sessions': {'open_auction', 'continuous_am', 'continuous_pm', 'close_auction', 'after_hours'},
    'stamp_duty': {'buy_rate', 'sell_rate', 'basis'}, 'transfer_fee': {'buy_rate', 'sell_rate', 'basis', 'minimum'},
}


def project(kind):
    if kind not in KINDS:
        raise ValueError('未知交易规则项目')
    return 'rules-' + kind.replace('_', '-')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def identity(row):
    return digest([row[k] for k in ('kind', 'market', 'board', 'condition_key', 'parameter_key', 'effective_start')])


def citation_identity(row):
    return digest([row[k] for k in ('source_url', 'document_hash', 'clause_key')])


def validate(kind, rows, citations):
    if kind not in KINDS or not isinstance(rows, list) or not 1 <= len(rows) <= 1000 or not isinstance(citations, list) or not 1 <= len(citations) <= 256:
        raise ValueError('交易规则集合为空或超过上限')
    refs = {}
    for c in citations:
        if set(c) != {'citation_key', *CITATION_COLUMNS} or c['citation_key'] != citation_identity(c) or c['citation_key'] in refs:
            raise ValueError('规则依据身份、字段或重复无效')
        for k, maximum in [('issuer', 100), ('title', 200), ('source_url', 1000), ('clause_key', 100), ('excerpt', 4000)]:
            if not isinstance(c[k], str) or not c[k].strip() or len(c[k]) > maximum:
                raise ValueError('规则依据字段为空或超限：' + k)
        if not re.fullmatch('[0-9a-f]{64}', c['document_hash']):
            raise ValueError('规则正文摘要无效')
        _date(c['published_date'])
        parsed = urlsplit(c['source_url'])
        if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password or not any(parsed.hostname == d or (parsed.hostname or '').endswith('.' + d) for d in ('sse.com.cn', 'szse.cn', 'bse.cn', 'gov.cn', 'chinatax.gov.cn', 'chinaclear.cn', 'chinagate.cn')):
            raise ValueError('规则依据必须属于官方来源')
        refs[c['citation_key']] = c
    keys, used = set(), set()
    for r in rows:
        if set(r) != {'record_key', *VALUE_COLUMNS} or r['record_key'] != identity(r) or r['record_key'] in keys or r['kind'] != kind:
            raise ValueError('规则参数字段、身份或重复无效')
        if r['market'] not in ('SH', 'SZ', 'BJ', 'CN') or r['board'] not in ('MAIN', 'STAR', 'CHINEXT', 'ALL') or r['parameter_key'] not in PARAMETERS[kind]:
            raise ValueError('规则参数市场、板块或名称无效')
        if not re.fullmatch('[a-z0-9_]{1,50}', r['condition_key']) or r['unit'] not in ('ratio', 'shares', 'CNY', 'Asia/Shanghai', 'text'):
            raise ValueError('规则条件或单位无效')
        _date(r['effective_start'])
        if r['effective_end'] is not None:
            _date(r['effective_end'])
            if r['effective_end'] < r['effective_start']:
                raise ValueError('规则生效区间倒置')
        if r['citation_key'] not in refs:
            raise ValueError('规则缺少必要官方依据')
        if r['number_value'] is not None:
            n = r['number_value']
            if not isinstance(n, str) or not re.fullmatch(r'\d{1,8}(?:\.\d{1,8})?', n) or not Decimal(n).is_finite():
                raise ValueError('规则数值必须使用有界精确十进制')
            if r['unit'] == 'ratio' and Decimal(n) > 1:
                raise ValueError('税率或涨跌比例单位错误')
            if r['parameter_key'] in ('price_tick', 'buy_minimum', 'buy_increment') and Decimal(n) <= 0:
                raise ValueError('价格档位及数量必须为正')
        if not isinstance(r['text_value'], str) or not r['text_value'].strip() or len(r['text_value']) > 200:
            raise ValueError('规则说明为空或超限')
        if (r['start_time'] is None) != (r['end_time'] is None):
            raise ValueError('交易时段必须有起止')
        if r['start_time'] is not None:
            if r['unit'] != 'Asia/Shanghai' or any(not isinstance(r[k], str) or time.fromisoformat(r[k]).isoformat() != r[k] for k in ('start_time', 'end_time')) or r['start_time'] >= r['end_time']:
                raise ValueError('交易时段单位或区间无效')
        if all(r[k] is None for k in ('number_value', 'start_time')) and r['unit'] != 'text':
            raise ValueError('规则数值缺失')
        keys.add(r['record_key'])
        used.add(r['citation_key'])
    if used != refs.keys():
        raise ValueError('规则有未使用或遗漏依据')
    if keys != EXPECTED.get(kind, {}).keys():
        raise ValueError('规则必要参数集合不完整或出现未审核身份')
    for row in rows:
        expected = EXPECTED[kind][row['record_key']]
        for key, value in expected.items():
            actual = row[key]
            if key == 'number_value' and value is not None and actual is not None:
                actual, value = Decimal(actual), Decimal(value)
            if actual != value:
                raise ValueError('规则参数超出已审核契约：' + key)
        ref = refs[row['citation_key']]
        if [ref['source_url'], ref['clause_key'], digest(ref['excerpt'])] != REFERENCES[kind][row['record_key']]:
            raise ValueError('官方条款变化或参数引用不符，须重新审核')
    if len(json.dumps([rows, citations], ensure_ascii=False).encode()) > 256 * 1024:
        raise ValueError('规则规范消息超过256KiB')
    return True


def _date(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value or not '1990-01-01' <= value <= '2100-01-01':
        raise ValueError('规则日期无效')


def payload(kind, rows, citations):
    rows = sorted(rows, key=lambda x: x['record_key'])
    citations = sorted(citations, key=lambda x: x['citation_key'])
    validate(kind, rows, citations)
    return dict(page=1, rows=rows, citations=citations)
