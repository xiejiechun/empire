"""Typed bounded SQL queries; coverage checks identities and canonical contents."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from empire.contracts.business_schema import schema_contract
from empire.contracts.listings import (
    COLUMNS,
    CONTRACT,
    DATASET,
    JOB,
    PROJECT,
    TABLE,
    date_warning,
    decode,
    digest,
    unavailable_proof,
    validate,
)
from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import CheckEvidence, PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.contracts.security import split_unified_code
from empire.core.time import CHINA
from empire.plugins.infra.collection_state import read_state


class ListingDataPlugin:
    manifest = PluginManifest('data.listings', '上市与发行资料查询', requires=('mysql.store',),
        provides=('listings.query',), description='当前首次上市资料；不声称全历史退市证券覆盖')
    preparation = (PreparationContribution('listings', 'listings.query', '同花顺', PROJECT, JOB,
        DATASET, 'collector.ths_listings', ('tests/test_ths_listings.py',),
        ('tests/integration/test_listing_archive.py',), scoped=True),)

    def __init__(self, namespace='empire'):
        self.namespace, self.mysql = namespace, None

    async def start(self, context):
        self.mysql = context.get('mysql.store')
        await self.mysql.require_schema(*schema_contract(TABLE, *COLUMNS, 'content_hash', 'contract_version', 'version_observed_at'))
        return {'listings.query': self}

    def _plan(self, conn):
        import re
        state = read_state(conn, self.namespace, PROJECT, 'ths')
        values = conn.execute(text('SELECT s.unified_code,s.name,l.listing_date,l.content_hash,l.contract_version '
            'FROM stock s LEFT JOIN stock_listing l USING(unified_code) ORDER BY s.unified_code LIMIT 15001')).mappings().all()
        keys = [r['unified_code'] for r in values]
        if not keys or len(keys) > 15000 or len(set(keys)) != len(keys):
            raise ValueError('当前股票池为空、重复或超限')
        stocks, existing = [], set()
        for r in values:
            market, code = split_unified_code(r['unified_code'])
            stocks.append(dict(market=market, code=code, name=r['name']))
            unit = market + ':' + code
            proof = state.get('units', {}).get(unit, {})
            if (not unavailable_proof(proof) and r['listing_date'] and re.fullmatch('[0-9a-f]{64}', r['content_hash'] or '')
                    and r['contract_version'] == CONTRACT and proof.get('contract') == CONTRACT
                    and proof.get('digest') == r['content_hash']):
                existing.add(market + ':' + code)
        proof = state.get('manifest', {}) if state.get('contract_version') == CONTRACT else {}
        return stocks, existing, proof

    async def plan(self):
        def read():
            with self.mysql.read_engine.begin() as conn:
                return self._plan(conn)
        return await self.mysql.read(read)

    async def list_records(self, code='', start='', end='', after=None, limit=200):
        import re
        if not isinstance(code, str) or not re.fullmatch('[0-9]{0,6}', code) or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('上市查询代码或上限无效')
        scope = PreparationScope.parse(dict(start=start, end=end))
        clauses, params = [], dict(limit=limit + 1)
        if code:
            clauses.append('l.unified_code LIKE :code')
            params['code'] = code + '%'
        for day, op, key in ((scope.start, '>=', 'start'), (scope.end, '<=', 'end')):
            if day:
                clauses.append('l.listing_date' + op + ':' + key)
                params[key] = day
        if after is not None:
            from datetime import date
            if not isinstance(after, (list, tuple)) or len(after) != 2:
                raise ValueError('上市分页游标无效')
            date.fromisoformat(after[0])
            split_unified_code(after[1])
            clauses.append('(l.listing_date,l.unified_code)>(:day,:security)')
            params.update(day=after[0], security=after[1])
        projection = ','.join('l.' + k for k in COLUMNS if k != 'history')
        def read():
            with self.mysql.read_engine.begin() as conn:
                state = read_state(conn, self.namespace, PROJECT, 'ths')
                unavailable = {unit.split(':')[1] + '.' + unit.split(':')[0]
                    for unit, proof in state.get('units', {}).items() if unavailable_proof(proof)}
                values = conn.execute(text(f'SELECT {projection},s.name FROM {TABLE} l LEFT JOIN stock s USING(unified_code) '
                    + ('WHERE ' + ' AND '.join(clauses) if clauses else '')
                    + ' ORDER BY l.listing_date,l.unified_code LIMIT :limit'), params).mappings().all()
                rows = [{k: str(v) if v is not None else None for k, v in r.items()} for r in values[:limit]]
                for row in rows:
                    row['detail_status'] = 'unavailable' if row['unified_code'] in unavailable else 'available'
                last = rows[-1] if rows else None
                return dict(rows=rows, next=[last['listing_date'], last['unified_code']] if len(values) > limit else None,
                    unavailable_count=sum(k.startswith(code) for k in unavailable))
        return await self.mysql.read(read)

    async def detail(self, security):
        split_unified_code(security)
        def read():
            with self.mysql.read_engine.begin() as conn:
                row = conn.execute(text(f'SELECT * FROM {TABLE} WHERE unified_code=:code'), {'code': security}).mappings().first()
                market, code = split_unified_code(security)
                proof = read_state(conn, self.namespace, PROJECT, 'ths').get('units', {}).get(market + ':' + code, {})
                if unavailable_proof(proof):
                    return dict(unified_code=security, detail_status='unavailable', source_status_code=10001,
                                last_valid=decode(row) if row else None)
                return decode(row) if row else None
        return await self.mysql.read(read)

    async def preparation_check(self, request=None):
        scope = PreparationScope.parse(request)
        def read():
            with self.mysql.read_engine.begin() as conn:
                stocks, _, proof = self._plan(conn)
                state = read_state(conn, self.namespace, PROJECT, 'ths')
                unavailable = {unit.split(':')[1] + '.' + unit.split(':')[0]
                    for unit, unit_proof in state.get('units', {}).items() if unavailable_proof(unit_proof)}
                expected = {s['code'] + '.' + s['market'] for s in stocks if not scope.codes or s['code'] in scope.codes}
                if scope.codes:
                    # Stored retired identities remain queryable and selectable.
                    expected |= {r[0] for r in conn.execute(text('SELECT unified_code FROM stock_listing')).all() if r[0][:6] in scope.codes}
                actual, invalid, after, conflicts = set(), [], '', 0
                while True:
                    rows = conn.execute(text(f'SELECT * FROM {TABLE} WHERE unified_code>:after ORDER BY unified_code LIMIT 200'), {'after': after}).mappings().all()
                    for row in rows:
                        if row['unified_code'] not in expected:
                            continue
                        actual.add(row['unified_code'])
                        try:
                            normalized = validate(decode(row), datetime.now(CHINA).date().isoformat())
                            conflicts += int(date_warning(normalized))
                            if row['contract_version'] != CONTRACT or digest(normalized) != row['content_hash']:
                                raise ValueError('上市内容或契约证明不符')
                        except (ValueError, TypeError, KeyError):
                            invalid.append(row['unified_code'])
                    if len(rows) < 200:
                        break
                    after = rows[-1]['unified_code']
                missing = expected - actual
                unknown = set(scope.codes) - {k[:6] for k in expected}
                return expected, missing, unknown, invalid, proof, conflicts, unavailable & expected
        expected, missing, unknown, invalid, proof, conflicts, unavailable = await self.mysql.read(read)
        complete = bool(expected) and not missing and not unknown and not invalid and not unavailable
        try:
            age = datetime.now(UTC) - datetime.fromisoformat(proof['refresh_started_at'])
            fresh = timedelta(0) <= age <= timedelta(days=8)
        except (ValueError, TypeError, KeyError):
            fresh = False
        info = f'检查{len(expected)}证券；缺记录{len(missing)}，来源暂无资料{len(unavailable)}，未知证券{len(unknown)}，内容错误{len(invalid)}；来源成立日晚于上市日{conflicts}条（附加字段警告，保留原值）；当前池及已存记录，不包含从未采集的退市证券'
        return tuple(CheckEvidence(k, 'unknown' if k == 'coverage' and complete and not scope.codes
            else 'pass' if ok else 'fail', info + '；' + note, blocking=blocking)
            for k, ok, note, blocking in (
                ('fields', complete, '上市日必需；发行附加字段来源NULL保留', True),
                ('keys', complete, '统一代码主键及规范内容摘要核对', True),
                ('coverage', complete, '按键集合检查；指定证券可单独核验，全历史含退市范围没有完整证明', True),
                ('quality', complete, '日期、单位、精度、完整字段及正文核验', True),
                ('freshness', complete and fresh, '八天内全池复核；普通轮次仅补缺', True),
                ('temporal', complete, '上市日可作交易起点；不提供历史修订版本或全市场退市覆盖', False)))

    async def stop(self):
        self.mysql = None

    def health(self):
        return {'status': 'ok' if self.mysql else 'stopped'}
