"""Bounded theme queries; source history and archived daily lists stay distinct."""
import json
from datetime import UTC, date, datetime, time

from sqlalchemy import text

from empire.contracts.plugin import PluginManifest
from empire.core.time import CHINA
from empire.features.themes.dataset import ThemeDetailDataset
from empire.features.themes.detail_model import source_id
from empire.features.themes.history import ThemeHistory
from empire.features.themes.history_model import digest, directory
from empire.features.themes.repository import TABLE_COLUMNS, read_detail
from empire.features.themes.storage_contract import DAILY_FIELDS, decode_daily, security_map
from empire.plugins.infra.query_order import column_fields, ordered_page
from empire.plugins.infra.schema_manifest import schema_contract
from empire.plugins.pipeline.fingerprints import FingerprintCache


def daily_review_due(observed, now):
    local_now, local_observed = now.astimezone(CHINA), observed.astimezone(CHINA)
    cutoff = datetime.combine(local_now.date(), time(15, 30), CHINA)
    return local_observed.date() < local_now.date() or local_now >= cutoff > local_observed


class ThemeDataPlugin:
    manifest = PluginManifest('data.themes', '题材查询', requires=('mysql.store', 'redis.store'),
                              provides=('themes.query',))

    def __init__(self, archive_settings):
        self.archive_settings = archive_settings
        self.mysql = None

    async def start(self, context):
        self.mysql, self.store = context.get('mysql.store'), context.get('redis.store')
        await self.mysql.require_schema(*schema_contract(TABLE_COLUMNS))
        self.history = ThemeHistory(self.store.client, self.store.prefix)
        self.fingerprints = FingerprintCache(self.store, self.archive_settings,
                                             lambda _: ThemeDetailDataset.FINGERPRINT_VERSION)
        return {'themes.query': self}

    async def current(self):
        today = datetime.now(CHINA).date()
        raw = await self.store.client.get(self.history.keys(today)[0])
        if raw is None:
            return None
        value = json.loads(raw)
        rows = directory(list(value['rows'].values()))
        if rows != value['rows'] or digest(rows) != value['digest']:
            raise ValueError('当前题材目录损坏，须重新完整采样')
        if datetime.fromisoformat(value['at']).astimezone(CHINA).date() != today:
            return None
        return {**value, 'rows': list(rows.values())}

    async def intraday(self, day, at=''):
        return await self.history.snapshot(date.fromisoformat(day), at=datetime.fromisoformat(at) if at else None)

    async def daily(self, day, after='', limit=200, order=None):
        date.fromisoformat(day)
        if type(limit) is not int or not 1 <= limit <= 200 or (order is None and (not isinstance(after, str) or len(after) > 65)):
            raise ValueError('题材列表查询界限错误')
        def read():
            with self.mysql.read_engine.connect() as conn:
                if order is not None:
                    records, cursor = ordered_page(
                        conn, f'SELECT {",".join(DAILY_FIELDS)},observed_at FROM theme_daily WHERE business_date=:day',
                        dict(day=day), order=order, fields=column_fields((*DAILY_FIELDS, 'observed_at')),
                        identity=('theme_id',), after=after or None, limit=limit,
                    )
                    return dict(rows=[decode_daily(r) for r in records], next=cursor)
                records = conn.execute(text(f'SELECT {",".join(DAILY_FIELDS)},observed_at FROM theme_daily '
                    'WHERE business_date=:day AND theme_id>:after ORDER BY theme_id LIMIT :limit'),
                    dict(day=day, after=after, limit=limit + 1)).mappings().all()
                return dict(rows=[decode_daily(r) for r in records[:limit]],
                            next=records[limit - 1]['theme_id'] if len(records) > limit else None)
        return await self.mysql.read(read)

    async def detail(self, theme_id):
        source_id(theme_id)
        def read():
            with self.mysql.read_engine.connect() as conn:
                head, detail = read_detail(conn, theme_id)
                if head and digest(detail) != head['content_sha256']:
                    raise ValueError('题材详情正文与摘要不符')
                return None if not head else dict(detail=detail, observed_at=head['observed_at'].isoformat())
        return await self.mysql.read(read)

    async def detail_page(self, theme_id, after='', limit=200, order=None):
        source_id(theme_id)
        if type(limit) is not int or not 1 <= limit <= 200 or (order is None and (not isinstance(after, str) or len(after) > 64)):
            raise ValueError('题材详情分页界限错误')
        def read():
            with self.mysql.read_engine.connect() as conn:
                head = conn.execute(text('SELECT theme_id,name,brief,introduction,observed_at FROM theme_detail '
                                         'WHERE theme_id=:id'), {'id': theme_id}).mappings().one_or_none()
                if head is None:
                    return None
                if order is not None:
                    records, cursor = ordered_page(
                        conn, 'SELECT r.*,s.name AS stock_name,c.name AS category_name '
                        'FROM theme_stock_reason r LEFT JOIN theme_stock s ON r.theme_id=s.theme_id '
                        'AND r.unified_code=s.unified_code LEFT JOIN theme_category c ON r.theme_id=c.theme_id '
                        'AND r.category_id=c.category_id WHERE r.theme_id=:id', dict(id=theme_id),
                        order=order, fields=column_fields((*TABLE_COLUMNS['theme_stock_reason'], 'stock_name', 'category_name')),
                        identity=('relation_id',), after=after or None, limit=limit,
                    )
                    if any(r['stock_name'] is None or r['category_id'] is not None and r['category_name'] is None for r in records):
                        raise ValueError('题材详情缺失必需企业或分类关联')
                    return dict(head=dict(head), rows=records, next=cursor)
                records = conn.execute(text('SELECT r.*,s.name AS stock_name,c.name AS category_name '
                    'FROM theme_stock_reason r LEFT JOIN theme_stock s ON r.theme_id=s.theme_id '
                    'AND r.unified_code=s.unified_code LEFT JOIN theme_category c ON r.theme_id=c.theme_id '
                    'AND r.category_id=c.category_id WHERE r.theme_id=:id AND r.relation_id>:after '
                    'ORDER BY r.relation_id LIMIT :limit'), dict(id=theme_id, after=after, limit=limit + 1)).mappings().all()
                if any(r['stock_name'] is None or r['category_id'] is not None and r['category_name'] is None for r in records):
                    raise ValueError('题材详情缺失必需企业或分类关联')
                return dict(head=dict(head), rows=[dict(r) for r in records[:limit]],
                            next=records[limit - 1]['relation_id'] if len(records) > limit else None)
        return await self.mysql.read(read)

    async def identities(self):
        def read():
            with self.mysql.read_engine.connect() as conn:
                rows = conn.execute(text('SELECT unified_code FROM stock LIMIT 100001')).scalars().all()
                if len(rows) > 100000:
                    raise ValueError('证券目录超限')
                known = conn.execute(text('SELECT DISTINCT unified_code FROM theme_stock LIMIT 10001')).scalars().all()
                if len(known) > 10000:
                    raise ValueError('题材已核实证券身份集合超限')
                rows.extend(known)
                return security_map(rows)
        return await self.mysql.read(read)

    async def detail_plan(self, rows, *, fresh=False):
        roots = {r['theme_id']: r for r in rows if r['parent_id'] is None}
        def read():
            with self.mysql.read_engine.connect() as conn:
                values = conn.execute(text('SELECT theme_id,name,observed_at FROM theme_detail LIMIT 2001')).mappings().all()
                if len(values) > 2000:
                    raise ValueError('题材详情规划超限')
                return {r['theme_id']: r for r in values}
        heads = await self.mysql.read(read)
        if fresh:
            return sorted(roots)
        urgent = sorted(k for k, row in roots.items() if k not in heads or row['name'] != heads[k]['name'])
        proofs = await self.fingerprints.peek(ThemeDetailDataset.FINGERPRINT_NAMESPACE, 'kaipanla', sorted(roots))
        due, now = [], datetime.now(UTC)
        for key in roots.keys() & heads.keys():
            observed = heads[key]['observed_at'].replace(tzinfo=CHINA).astimezone(UTC)
            proof = proofs.get(key)
            if proof:
                observed = max(observed, datetime.fromisoformat(proof['version'][1]))
            if daily_review_due(observed, now) and key not in urgent:
                due.append((observed, key))
        # Complete the due set in one bounded daily round; no multi-round slicing.
        return urgent + [key for _, key in sorted(due)]

    async def stop(self):
        self.mysql = None

    def health(self):
        return {'status': 'ok' if self.mysql else 'stopped'}
