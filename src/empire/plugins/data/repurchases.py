"""SQL-only indexed browsing and canonical whole-source coverage audit."""
import asyncio
import re
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text

from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import CheckEvidence, PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.contracts.repurchases import (
    COLUMNS,
    DATASET,
    DATES,
    JOB,
    MAX_ROWS,
    NUMBERS,
    PROJECT,
    TEXTS,
    extend_digest,
    validate,
)
from empire.contracts.security import split_unified_code
from empire.plugins.datasets import repurchases as mapping
from empire.plugins.infra.collection_state import read_state

LIST_COLUMNS = tuple(k for k in COLUMNS if k not in TEXTS)


def public(row):
    r = dict(row)
    for k in DATES:
        if k in r and r[k] is not None:
            r[k] = r[k].isoformat()
    for k in NUMBERS:
        if k in r and r[k] is not None:
            from empire.contracts.repurchases import number
            r[k] = number(r[k])
    return r


class RepurchaseDataPlugin:
    manifest = PluginManifest('data.repurchases', '股票回购查询', requires=('mysql.store',),
        provides=('repurchases.query',), description='方案范围、详情与完整来源集合核验')
    preparation = (PreparationContribution('repurchases', 'repurchases.query', '东方财富', PROJECT,
        JOB, DATASET, 'collector.eastmoney_repurchase', ('tests/test_repurchases.py',),
        ('tests/integration/test_repurchase_archive.py',), scoped=True),)

    def __init__(self, namespace='empire'):
        self.namespace = namespace

    async def start(self, context):
        self.context = context
        self.mysql = context.get('mysql.store')
        await self.mysql.require_schema(mapping.TABLES, mapping.KEYS)
        return {'repurchases.query': self}

    async def list_plans(self, code='', start='', end='', progress='', after=None, limit=200):
        if (not isinstance(code, str) or not re.fullmatch(r'(?:[0-9]{0,6}|[0-9]{6}\.(?:SH|SZ|BJ))', code)
                or not isinstance(progress, str) or not re.fullmatch(r'[0-9]{0,16}', progress)
                or type(limit) is not int or not 1 <= limit <= 200):
            raise ValueError('回购查询参数无效')
        scope = PreparationScope.parse(dict(start=start, end=end))
        clauses, params = ['1=1'], dict(limit=limit + 1)
        if code:
            clauses.append('unified_code LIKE :code')
            params['code'] = code if '.' in code else code + '%'
        if progress:
            clauses.append('progress_code=:progress')
            params['progress'] = progress
        for bound, op, key in ((scope.start, '>=', 'start'), (scope.end, '<=', 'end')):
            if bound:
                clauses.append('plan_date' + op + ':' + key)
                params[key] = bound
        if after is not None:
            if (not isinstance(after, (tuple, list)) or len(after) != 2 or
                    not isinstance(after[1], str) or not re.fullmatch(r'[1-9][0-9]{0,19}', after[1])):
                raise ValueError('回购分页游标无效')
            date.fromisoformat(after[0])
            clauses.append('(plan_date,plan_id)<(:day,:identity)')
            params.update(day=after[0], identity=after[1])
        def read():
            with self.mysql.read_engine.connect() as conn:
                values = conn.execute(text(f'SELECT {",".join(LIST_COLUMNS)} FROM {mapping.TABLE} '
                    f'WHERE {" AND ".join(clauses)} ORDER BY plan_date DESC,plan_id DESC LIMIT :limit'), params).mappings().all()
                rows = [public(r) for r in values[:limit]]
                last = rows[-1] if rows else None
                return dict(rows=rows, next=[last['plan_date'], last['plan_id']] if len(values) > limit else None)
        return await self.mysql.read(read)

    async def detail(self, plan_id):
        if not isinstance(plan_id, str) or not re.fullmatch(r'[1-9][0-9]{0,19}', plan_id):
            raise ValueError('回购方案编号无效')
        def read():
            with self.mysql.read_engine.connect() as conn:
                row = conn.execute(text(f'SELECT {",".join(COLUMNS)} FROM {mapping.TABLE} WHERE plan_id=:id'),
                                   {'id': plan_id}).mappings().first()
                return public(row) if row else None
        return await self.mysql.read(read)

    def audit(self):
        count, summary, after, invalid, last = 0, '0'*64, '', 0, None
        with self.mysql.read_engine.begin() as conn:
            state = read_state(conn, self.namespace, PROJECT, 'eastmoney')
            while True:
                records = conn.execute(text(f'SELECT * FROM {mapping.TABLE} WHERE plan_id>:after '
                    'ORDER BY plan_id LIMIT 200'), {'after': after}).mappings().all()
                if not records:
                    break
                canonical = []
                for record in records:
                    row = validate({k: record[k] for k in COLUMNS})
                    from empire.contracts.repurchases import digest
                    invalid += digest(row) != record['content_hash']
                    canonical.append(row)
                summary = extend_digest(summary, canonical)
                count += len(records)
                after, last = records[-1]['plan_id'], canonical[-1]
                if count > MAX_ROWS:
                    raise ValueError('回购业务行数超过声明审计范围')
        proof = state.get('coverage', {})
        valid = proof.get('contract') == 1 and proof.get('count') == count and proof.get('digest') == summary and invalid == 0
        return dict(count=count, digest=summary, valid=valid, proof=proof, last=last, invalid=invalid)

    async def preparation_check(self, request=None):
        scope = PreparationScope.parse(request)
        for code in scope.codes:
            if '.' in code:
                split_unified_code(code)
        audit = await self.mysql.read(self.audit)
        valid, count = audit['valid'], audit['count']
        try:
            stamp = datetime.fromisoformat(audit['proof']['observed_at'])
            ingest = self.context.optional('ingest.publish')
            if valid and ingest:
                try:
                    current = (await asyncio.wait_for(ingest.checkpoint(JOB), 3))['cursor']
                    if (current.get('phase') == 'complete' and current.get('contract') == 1
                            and current.get('total') == count and current.get('digest') == audit['digest']):
                        newer = datetime.fromisoformat(current['completed_at'])
                        if newer.tzinfo is not None and stamp <= newer <= datetime.now(UTC):
                            stamp = newer
                except Exception:
                    pass
            fresh = stamp.tzinfo is not None and timedelta(0) <= datetime.now(UTC) - stamp <= timedelta(days=3)
        except (KeyError, ValueError, TypeError):
            fresh = False
        def evidence(key, ok, message):
            return CheckEvidence(key, 'pass' if ok else 'fail', message)
        return (
            evidence('fields', valid, f'{count}方案；身份、日期、数量金额及来源说明逐行校验；NULL保持未知'),
            evidence('keys', valid, '唯一来源方案编号；完整SQL键与规范内容滚动摘要匹配'),
            evidence('coverage', valid, '完整来源集合与SQL逐行摘要核对；不是依据最大日期或条数推断完整'),
            evidence('quality', valid, '计划与累计实际分开，未知状态保留；回购完成不推断注销完成'),
            evidence('freshness', valid and fresh, 'SQL完整集合匹配后，以SQL或匹配完整已归档轮次的核验时间确认3天时效；Redis可选'),
            CheckEvidence('temporal', 'fail', '仅当前修订和公告自然日，无完整旧版本/日内时刻，不用于严格历史信号回放',
                          blocking=scope.purpose != 'analysis'),
        )

    async def stop(self):
        pass

    def health(self):
        return {'status': 'ready'}
