"""Bounded formal SQL directory reads, independent of Redis availability."""
import re

from sqlalchemy import text

from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.features.yuanhang_etf import catalog_dataset
from empire.features.yuanhang_etf.contract import (
    CATALOG_DATASET,
    CATALOG_PROJECT,
    ETF_LIMIT,
    digest,
)
from empire.plugins.infra.collection_state import read_state
from empire.plugins.infra.query_order import column_fields, ordered_page

TESTS = ('tests/test_yuanhang_etf.py',)
INTEGRATION = ('tests/integration/test_yuanhang_etf_archive.py',)


class CatalogQuery:
    manifest = PluginManifest('data.yuanhang_etfs', '远航ETF目录查询', requires=('mysql.store',),
        provides=('yuanhang.etfs.query',))
    preparation = (PreparationContribution('etf_catalog', 'yuanhang.etfs.query', '同花顺远航版',
        CATALOG_PROJECT, CATALOG_PROJECT + '-v1', CATALOG_DATASET, 'collector.yuanhang_etfs', TESTS, INTEGRATION, scoped=True),)
    project_id = CATALOG_PROJECT

    def __init__(self, namespace='empire', archive_settings=None):
        self.namespace, self.archive_settings = namespace, archive_settings or {}
        self.context = self.mysql = None

    async def start(self, context):
        self.context, self.mysql = context, context.get('mysql.store')
        await self.mysql.require_schema(catalog_dataset.TABLES, catalog_dataset.KEYS)
        return {'yuanhang.etfs.query': self}

    async def read(self, operation):
        def read():
            with self.mysql.read_engine.begin() as conn:
                return operation(conn)
        return await self.mysql.read(read)

    async def catalog(self, codes=None):
        if codes is not None:
            if not isinstance(codes, (list, tuple)) or not 1 <= len(codes) <= ETF_LIMIT or len(codes) != len(set(codes)):
                raise ValueError('ETF采集范围无效')
            for code in codes:
                if not isinstance(code, str) or not re.fullmatch(r'[0-9]{6}(?:\.(SH|SZ))?', code):
                    raise ValueError('ETF范围代码格式无效')
        def read(conn):
            rows = [dict(r) for r in conn.execute(text('SELECT unified_code AS code,name,native_market FROM yuanhang_etf '
                'WHERE active=TRUE ORDER BY unified_code LIMIT 5001')).mappings()]
            state = read_state(conn, self.namespace, CATALOG_PROJECT, 'ths_yuanhang')
            if not rows or len(rows) > ETF_LIMIT or state.get('catalog_hash') != digest(rows) or state.get('count') != len(rows):
                raise ValueError('ETF目录未准备或集合证明不匹配，请先采集ETF目录')
            if codes is None:
                return rows
            selected, seen = [], set()
            for row in rows:
                matching = {c for c in codes if c in (row['code'], row['code'][:6])}
                if matching:
                    selected.append(row)
                    seen.update(matching)
            if seen != set(codes) or len(selected) != len(codes):
                raise ValueError('指定ETF不在当前目录或选择身份重复')
            return selected
        return await self.read(read)

    async def browse(self, code='', search='', market='', after=None, limit=200, order=None):
        if (not isinstance(search, str) or len(search) > 100 or not isinstance(code, str) or len(code) > 9
                or market not in ('', 'SH', 'SZ') or type(limit) is not int or not 1 <= limit <= 500):
            raise ValueError('ETF目录查询范围无效')
        def escape(value):
            return '%' + value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        def read(conn):
            rows, cursor = ordered_page(conn,
                'SELECT unified_code,name,native_market FROM yuanhang_etf WHERE active=TRUE '
                'AND (name LIKE :search OR CONVERT(unified_code USING utf8mb4) LIKE :search) '
                "AND unified_code LIKE :code AND (:market='' OR RIGHT(unified_code,2)=:market)",
                dict(code=escape(code), search=escape(search), market=market),
                fields=column_fields(('unified_code', 'name', 'native_market')), identity=('unified_code',),
                order=order or {'field': 'unified_code', 'direction': 'asc'}, after=after, limit=limit)
            return dict(rows=rows, next=cursor)
        return await self.read(read)

    async def preparation_check(self, request=None):
        from empire.features.yuanhang_etf.audits import catalog_checks
        return await catalog_checks(self, PreparationScope.parse(request))

    async def stop(self):
        self.mysql = self.context = None

    def health(self):
        return {'status': 'ok' if self.mysql else 'stopped'}
