"""Official document discovery, shared bounded downloads and reviewed interpretation."""
import asyncio
import hashlib
import re
import time

from empire.contracts.plugin import PluginManifest
from empire.features.trading_rules.bse import BJ_FIELDS, BJ_FILE, BJ_LIST, BJ_NOTICE, BJ_RESUMED
from empire.features.trading_rules.bse import directory as bj_directory
from empire.features.trading_rules.bse import notice as bj_notice
from empire.features.trading_rules.documents import (
    RuleDocument,
    compact,
    docx_document,
    html_document,
    official_url,
)
from empire.features.trading_rules.parameters import Parameters, exchange_parameters
from empire.plugins.collection.unit_prefetch import DeferredResponse, prefetch_units

SH_LIST = 'https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/'
SH_NOTICE = SH_LIST + 'c/c_20260424_10816492.shtml'
SH_FILE = SH_LIST + 'c/10816492/files/58bd5ce4dfc94b57a5391f60eb2719ab.docx'
SH_DEFERRED = SH_LIST + 'c/10816492/files/7476908baade49b8b14881439d2f89b6.docx'
SZ_LIST = 'https://www.szse.cn/api/search/content'
SZ_NOTICE = 'https://www.szse.cn/lawrules/rule/trade/current/t20260424_620190.html'
SZ_FILE = 'https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf'
TAX_LAW = 'https://fgk.chinatax.gov.cn/zcfgk/c100009/c5193058/content.html'
TAX_RATE = 'https://tianjin.chinatax.gov.cn/11200000000/0300/030005/20220725150235434.shtml'
TAX_HALF = 'https://www.gov.cn/zhengce/zhengceku/202308/content_6900443.htm'
FEE_LIST = 'https://www.chinaclear.cn/zdjs/fbzyls/service_tlist/code_0.shtml'
FEE_ANNOUNCEMENT = 'http://cn.chinagate.cn/news/2022-04/29/content_78193990.htm'
DOMAINS = ('sse.com.cn', 'szse.cn', 'bse.cn', 'chinatax.gov.cn', 'gov.cn', 'chinaclear.cn', 'chinagate.cn')


def sh_directory(body):
    # SSE embeds the actual directory in @memo@ records, not visible anchors.
    raw = body.decode('utf-8')
    records = re.findall(r'(\d{4}-\d{2}-\d{2})\s*@memo@\s*([^@]+)@memo@\s*([^@]+)@doc@', raw)
    relevant = [(day, link.strip(), title.strip()) for day, link, title in records
                if re.fullmatch(r'上海证券交易所交易规则（\d{4}年修订）', title.strip())]
    if not relevant or len(relevant) > 100 or len({x[1] for x in relevant}) != len(relevant):
        raise ValueError('上交所规则目录为空、超限或重复')
    if max(x[0] for x in relevant) != '2026-04-24' or not any('10816492' in x[1] and x[0] == '2026-04-24' for x in relevant):
        raise ValueError('上交所交易规则版本变化，须核实新规则后更新解析契约')


def sz_directory(body):
    import json
    p = json.loads(body)
    rows = p.get('data')
    if not isinstance(rows, list) or p.get('totalSize') != len(rows) or not 1 <= len(rows) <= 20 or p.get('currentPage') != 1:
        raise ValueError('深交所规则目录分页或完整集合变化，不能沿用旧参数')
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('深交所目录同数异集或重复身份')
    relevant = [r for r in rows if re.fullmatch(r'.*发布.*深圳证券交易所交易规则.*', r['doctitle'])]
    if not relevant or max(int(r['id']) for r in relevant) != 620190:
        raise ValueError('深交所交易规则版本变化，须核实新规则')


def notice(body, market):
    value, links = html_document(body)
    text = compact(value)
    require = ('交易规则', '2026年', '2026年7月6日', '41号' if market == 'SH' else '551号')
    if any(x not in text for x in require) or ('尚未施行' in text and '现行有效' not in text):
        raise ValueError('交易规则发布、生效或现行状态无效')
    base, file = (SH_NOTICE, SH_FILE) if market == 'SH' else (SZ_NOTICE, SZ_FILE)
    urls = {official_url(base, href, DOMAINS) for href, title in links if href and ('.docx' in href or '.pdf' in href)}
    urls = {u.replace('http://', 'https://', 1) for u in urls}
    if file not in urls or (market == 'SH' and SH_DEFERRED not in urls):
        raise ValueError('交易规则必要附件集合不符')


def html_rule(body, *, issuer, title, url, published, effective, clauses):
    value, _, body_hash = body
    full = compact(value)
    if compact(title) not in full:
        raise ValueError('税费官方文档身份不符')
    resolved = {}
    for key, pattern in clauses.items():
        matches = re.findall(pattern, full)
        # Government pages repeat identical desktop/mobile/print article sections.
        if not 1 <= len(matches) <= 4 or len(set(matches)) != 1:
            raise ValueError('税费条款缺失或重复：' + key)
        resolved[key] = matches[0]
    return RuleDocument(issuer, title, url, published, effective, body_hash, resolved)


def stamp_parameters(law_body, rate_body, half_body):
    law = html_rule(law_body, issuer='全国人大常委会', title='中华人民共和国印花税法', url=TAX_LAW,
        published='2021-06-10', effective='2022-07-01', clauses={
            '第三条': r'第三条(.+?)第四条', '第五条': r'第五条(.+?)第六条'})
    rate = html_rule(rate_body, issuer='国家税务总局天津市税务局', title='证券交易的印花税税率是多少', url=TAX_RATE,
        published='2022-07-25', effective='2022-07-01', clauses={'法定税率': r'(根据《中华人民共和国印花税法》附件《印花税税目税率表》规定，证券交易，税率为成交金额的千分之一。)'})
    half = html_rule(half_body, issuer='财政部、税务总局', title='关于减半征收证券交易印花税的公告', url=TAX_HALF,
        published='2023-08-27', effective='2023-08-28', clauses={'减半征收': r'(自2023年8月28日起，证券交易印花税实施减半征收。)'})
    p = Parameters('stamp_duty')
    for doc, number, until in [(rate, '0.001', '2023-08-27'), (half, '0.0005', None)]:
        # New effective segment requires both base rate and reduction evidence.
        p.add(doc, '法定税率' if doc is rate else '减半征收', 'CN', 'ALL', 'sell_rate',
            'A股按成交金额向卖方征收；法定千分之一，2023-08-28起减半', number=number, unit='ratio', until=until)
    p.add(law, '第三条', 'CN', 'ALL', 'buy_rate', '对出让方征收，不对受让方征收',
        number='0', unit='ratio', fragments=('出让方征收', '不对受让方征收'))
    p.add(law, '第五条', 'CN', 'ALL', 'basis', '证券交易计税依据为成交金额', fragments=('成交金额',))
    return p.result()


def transfer_parameters(body):
    doc = html_rule(body, issuer='新华社（转述中国结算公告）',
        title='中国结算：4月29日起股票交易过户费总体下调50%', url=FEE_ANNOUNCEMENT,
        published='2022-04-29', effective='2022-04-29', clauses={
            '2022费率调整': r'(中国证券登记结算有限责任公司28日宣布，自2022年4月29日起，.+?按照成交金额0.01‰双向收取。)'})
    p = Parameters('transfer_fee')
    for market in ('SH', 'SZ', 'BJ'):
        for parameter in ('buy_rate', 'sell_rate'):
            p.add(doc, '2022费率调整', market, 'ALL', parameter,
                '2022-04-29调整公告费率；历史政策记录，尚未核实2026完整收费表',
                fragments=('沪深市场A股', '北京市场A股', '0.01‰双向收取'), number='0.00001', unit='ratio')
        p.add(doc, '2022费率调整', market, 'ALL', 'basis', '调整公告按成交金额收费；双向征收', fragments=('成交金额', '双向收取'))
        p.add(doc, '2022费率调整', market, 'ALL', 'minimum', '本公告未明确最低收费，保持未知；不填零', condition='unknown_minimum')
    return p


class RuleSources:
    manifest = PluginManifest('collector.rule_sources', '官方交易规则文档', requires=('http.fetch',),
        provides=('rules.source',), description='共享一分钟内已解析官方文档；成功原文不落盘')

    def __init__(self):
        self.cache, self.lock = {}, asyncio.Lock()

    async def start(self, context):
        self.http = context.get('http.fetch')
        return {'rules.source': self}

    async def fetch_group(self, owner, urls):
        results = {}
        async def download(url, *, reservation):
            kw = {}
            if url == SZ_LIST:
                kw['data'] = dict(keyword='', time=0, range='title', currentPage=1, pageSize=20,
                                  **{'channelCode[]': 'szserulestradeCurrency_news'})
            elif url == BJ_LIST:
                kw['data'] = {'keywords': '', 'startTime': '', 'endTime': '', 'nodeIds[]': '1304',
                              'page': '0', 'pageSize': '100', 'needFields[]': BJ_FIELDS}
            response = await self.http.request('POST' if kw else 'GET', url, **kw,
                headers={} if url in (BJ_LIST, BJ_NOTICE, BJ_RESUMED, BJ_FILE) else {'User-Agent': 'Mozilla/5.0'},
                allowed_domains=DOMAINS, project_id=owner.project_id,
                policy=self.http.response_policy('generic'), max_retries=owner.request_retries, reservation=reservation)
            async def consume():
                return decode_source(url, response.content)
            return DeferredResponse(response, consume)
        async with prefetch_units(owner, urls, download, url=urls[0], domains=DOMAINS, item_name='文件') as reads:
            async for index, read in reads:
                results[urls[index]] = await read.resolve()
        return results

    async def collect(self, owner):
        group = 'exchange' if owner.kind not in ('stamp_duty', 'transfer_fee') else owner.kind
        async with self.lock:
            cached = self.cache.get(group)
            if cached and time.monotonic() - cached[0] < 60:
                return cached[1][owner.kind]
            if group == 'exchange':
                bodies = await self.fetch_group(owner, [SH_LIST, SZ_LIST, SH_NOTICE, SZ_NOTICE, SH_FILE, SZ_FILE, SH_DEFERRED,
                                                       BJ_LIST, BJ_NOTICE, BJ_RESUMED, BJ_FILE])
                deferred = bodies[SH_DEFERRED]
                if any(x not in deferred for x in ('3.6.2', '3.6.3', '3.6.4', '3.6.9', '3.6.10')) or '3.7.2' in deferred:
                    raise ValueError('上交所暂缓条款集合变化，须重新核实')
                docs = [bodies[SH_FILE], bodies[SZ_FILE], bodies[BJ_FILE]]
                result = {kind: exchange_parameters(kind, *docs) for kind in
                          ('limit_rules', 'settlement_rules', 'lot_rules', 'tick_rules', 'sessions')}
            elif group == 'stamp_duty':
                bodies = await self.fetch_group(owner, [TAX_LAW, TAX_RATE, TAX_HALF])
                result = {group: stamp_parameters(bodies[TAX_LAW], bodies[TAX_RATE], bodies[TAX_HALF])}
            else:
                bodies = await self.fetch_group(owner, [FEE_ANNOUNCEMENT])
                result = {group: transfer_parameters(bodies[FEE_ANNOUNCEMENT]).result()}
            self.cache[group] = (time.monotonic(), result)
            return result[owner.kind]

    async def stop(self):
        self.cache.clear()

    def health(self):
        return {'status': 'ok', 'cached_groups': len(self.cache)}


def decode_source(url, body):
    if url == BJ_LIST:
        bj_directory(body)
        return True
    if url in (BJ_NOTICE, BJ_RESUMED):
        bj_notice(body, resumed=url == BJ_RESUMED)
        return True
    if url == BJ_FILE:
        return RuleDocument.decode(issuer='北京证券交易所', title='北京证券交易所交易规则',
            url=url, published='2026-04-24', effective='2026-07-06', body=body, format='docx')
    if url == SH_LIST:
        sh_directory(body)
        return True
    if url == SZ_LIST:
        sz_directory(body)
        return True
    if url in (SH_NOTICE, SZ_NOTICE):
        notice(body, 'SH' if url == SH_NOTICE else 'SZ')
        return True
    if url == SH_DEFERRED:
        return compact(docx_document(body))
    if url in (SH_FILE, SZ_FILE):
        market = '上海' if url == SH_FILE else '深圳'
        return RuleDocument.decode(issuer=market + '证券交易所', title=market + '证券交易所交易规则（2026年修订）',
            url=url, published='2026-04-24', effective='2026-07-06', body=body, format='docx' if url == SH_FILE else 'pdf')
    value, links = html_document(body)
    return value, links, hashlib.sha256(body).hexdigest()
