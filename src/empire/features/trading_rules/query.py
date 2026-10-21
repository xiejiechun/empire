"""Bounded MySQL rule queries, complete-set evidence and explicit coverage limits."""
import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import CheckEvidence, PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.features.trading_rules.contract import KINDS, SOURCE, digest, project, validate
from empire.features.trading_rules.dataset import (
    KEYS,
    TABLES,
    RuleDataset,
    canonical,
    read_snapshot,
)
from empire.plugins.infra.collection_state import read_state
from empire.plugins.pipeline.fingerprints import FingerprintCache


class RuleDataPlugin:
    def __init__(self, kind, namespace='empire', archive_settings=None):
        self.kind, self.namespace, self.archive_settings = kind, namespace, archive_settings or {}
        self.mapping = RuleDataset(kind)
        capability = 'rules.' + kind + '.query'
        self.manifest = PluginManifest('data.rules_' + kind, KINDS[kind] + '查询', requires=('mysql.store',),
            provides=(capability,), description='官方参数与引用；历史及市场缺口单独报告')
        self.preparation = (PreparationContribution(kind, capability, '官方交易所及税务机关', project(kind),
            self.mapping.JOB, next(iter(self.mapping.DATASETS)), 'collector.rules_' + kind,
            ('tests/test_trading_rules.py',), ('tests/integration/test_rule_archive.py',), scoped=True),)
        self.mysql = self.context = None

    async def start(self, context):
        self.mysql, self.context = context.get('mysql.store'), context
        await self.mysql.require_schema(TABLES, KEYS)
        return {self.manifest.provides[0]: self}

    async def list_rules(self, market='', after=None, limit=200):
        import re
        if market not in ('', 'SH', 'SZ', 'BJ', 'CN') or type(limit) is not int or not 1 <= limit <= 200 or (after is not None and not re.fullmatch('[0-9a-f]{64}', after)):
            raise ValueError('规则查询市场、页数或游标无效')
        def read():
            with self.mysql.read_engine.connect() as conn:
                where, args = 'kind=:kind', dict(kind=self.kind, limit=limit + 1)
                if market:
                    where += ' AND market=:market'
                    args['market'] = market
                if after:
                    where += ' AND record_key>:after'
                    args['after'] = after
                result = conn.execute(text('SELECT * FROM trading_rule_value WHERE ' + where + ' ORDER BY record_key LIMIT :limit'), args).mappings().all()
                values = [canonical(r) for r in result[:limit]]
                return dict(rows=values, next=values[-1]['record_key'] if len(result) > limit else None)
        return await self.mysql.read(read)

    async def citation(self, key):
        import re
        if not isinstance(key, str) or not re.fullmatch('[0-9a-f]{64}', key):
            raise ValueError('规则引用身份无效')
        def read():
            with self.mysql.read_engine.connect() as conn:
                row = conn.execute(text('SELECT c.* FROM trading_rule_citation c JOIN trading_rule_value v USING(citation_key) WHERE c.citation_key=:key AND v.kind=:kind LIMIT 1'), dict(key=key, kind=self.kind)).mappings().first()
                return canonical(row) if row else None
        return await self.mysql.read(read)

    def snapshot(self):
        with self.mysql.read_engine.begin() as conn:
            rows, citations = read_snapshot(conn, self.kind)
            state = read_state(conn, self.namespace, project(self.kind), SOURCE)
            return rows, citations, state

    async def preparation_check(self, request=None):
        scope = PreparationScope.parse(request)
        rows, citations, state = await self.mysql.read(self.snapshot)
        now, complete, stamp = datetime.now(UTC), False, state.get('observed_at', '')
        try:
            validate(self.kind, rows, citations)
            complete = state.get('contract') == 1 and state.get('digest') == digest([rows, citations]) and state.get('row_count') == len(rows)
            self.mapping.FINGERPRINT_VERSION.key([stamp], now=now)
        except (ValueError, TypeError, KeyError):
            complete = False
        if complete and self.context.optional('redis.store'):
            cache = FingerprintCache(self.context.get('redis.store'), self.archive_settings, lambda _: self.mapping.FINGERPRINT_VERSION)
            try:
                cached = (await asyncio.wait_for(cache.peek(self.mapping.FINGERPRINT_NAMESPACE, SOURCE, [self.kind]), 3)).get(self.kind, {})
                newer = self.mapping.FINGERPRINT_VERSION.key(cached['version'], now=now)[0]
                if cached['hash'] == digest([rows, citations]) and newer.isoformat(timespec='microseconds') >= stamp:
                    stamp = newer.isoformat(timespec='microseconds')
            except Exception:
                pass
        tax = self.kind in ('stamp_duty', 'transfer_fee')
        earliest = '2022-07-01' if tax else '2026-07-06'
        historical = bool(scope.start and scope.start < earliest)
        # Empty securities means the full A-share pool including Beijing.
        beijing = not tax and (not scope.codes or any(c.startswith(('4', '8', '9')) for c in scope.codes))
        covered = complete and not historical and self.kind != 'transfer_fee'
        limitation = ('印花税从2022-07-01起；法定税率及2023减半政策，非政策目录全集' if self.kind == 'stamp_duty' else
                      '过户费仅保存2022-04-29新华社转述的调整公告；最低收费及2026现行附件尚未核实' if self.kind == 'transfer_fee' else
                      '沪深北2026-07-06起普通竞价条款；北交所盘后仍暂缓；早期历史不在本次范围')
        fresh = False
        try:
            age = now - self.mapping.FINGERPRINT_VERSION.key([stamp], now=now)[0]
            fresh = complete and timedelta(0) <= age <= timedelta(days=4)
        except (ValueError, TypeError):
            pass
        usable = complete and self.kind not in ('settlement_rules', 'lot_rules', 'transfer_fee') and not (self.kind == 'limit_rules' and beijing)
        quality = ('交收前禁卖原文已保存；数值T+1交收依据尚缺' if self.kind == 'settlement_rules' else
                   '科创板200股及上限、北交所100股及上限已保存；当前递增股数仍需明确依据' if self.kind == 'lot_rules' else
                   '北交所30%及首日豁免已保存；涨跌价格舍入规则尚需核实' if self.kind == 'limit_rules' and beijing else limitation)
        def e(key, ok, message):
            return CheckEvidence(key, 'pass' if ok else 'fail', message)
        return (e('fields', complete and usable, quality if not usable else '类型、单位、生效段及关联官方依据完整'),
            e('keys', complete, '规范业务键集合及全部引用与同事务归档证明一致'),
            e('coverage', covered, limitation + ('；所选历史起点超出已核实范围' if historical else '')),
            e('quality', usable, quality), e('freshness', fresh and self.kind != 'transfer_fee', '固定文件及交易所目录每3天复查；允许1天执行余量；过户费原公告复查不证明现行收费表已核实'),
            e('temporal', covered and usable, '按生效段读取，现行规则不回填早期；未知终止不代表永久有效'))

    async def stop(self):
        self.mysql = self.context = None

    def health(self):
        return {'status': 'ok' if self.mysql else 'stopped'}
