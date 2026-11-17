"""One formal native catalogue/current-web-member read path."""

import re

from sqlalchemy import text

from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.contracts.security import index_code
from empire.features.yuanhang_indices import catalog_dataset, member_dataset
from empire.features.yuanhang_indices.audits import catalog_checks, member_checks
from empire.features.yuanhang_indices.contract import (
    CATALOG_DATASET,
    CATALOG_PROJECT,
    MEMBER_DATASET,
    MEMBER_PROJECT,
    digest,
)
from empire.plugins.infra.collection_state import read_state
from empire.plugins.infra.query_order import column_fields, ordered_page

TESTS = ('tests/test_yuanhang_indices.py',)
INTEGRATION = ('tests/integration/test_yuanhang_index_archive.py',)


class CatalogQuery:
    manifest = PluginManifest('data.yuanhang_indices', '远航指数目录查询', requires=('mysql.store',),
        provides=('yuanhang.indices.query',))
    preparation = (PreparationContribution('index_catalog', 'yuanhang.indices.query', '同花顺远航版',
        CATALOG_PROJECT, CATALOG_PROJECT + '-v1', CATALOG_DATASET, 'collector.yuanhang_indices', TESTS, INTEGRATION, scoped=True),)

    project_id = CATALOG_PROJECT

    def __init__(self, namespace='empire', archive_settings=None):
        self.namespace = namespace
        self.context = None
        self.archive_settings = archive_settings or {}

    async def start(self, context):
        self.context = context
        self.mysql = context.get('mysql.store')
        await self.mysql.require_schema(catalog_dataset.TABLES, catalog_dataset.KEYS)
        return {'yuanhang.indices.query': self}

    async def read(self, operation):
        def read():
            with self.mysql.read_engine.begin() as conn:
                return operation(conn)
        return await self.mysql.read(read)

    async def catalog(self, codes=None):
        if codes is not None:
            if not isinstance(codes, (list, tuple)) or not 1 <= len(codes) <= 1000 or len(codes) != len(set(codes)):
                raise ValueError('指数采集范围无效')
            for code in codes:
                index_code(code)
        def read(conn):
            rows = [dict(r) for r in conn.execute(text('SELECT index_code AS code,name,native_market FROM yuanhang_index '
                'WHERE active=TRUE ORDER BY index_code LIMIT 1001')).mappings()]
            state = read_state(conn, self.namespace, CATALOG_PROJECT, 'ths_yuanhang')
            if not rows or len(rows) > 1000 or state.get('catalog_hash') != digest(rows) or state.get('count') != len(rows):
                raise ValueError('远航指数目录未准备或集合证明不匹配，请先采集指数目录')
            if codes is not None and set(codes) - {r['code'] for r in rows}:
                raise ValueError('指定指数不在当前远航目录中')
            return [r for r in rows if codes is None or r['code'] in codes]
        return await self.read(read)

    async def browse(self, mode='indices', search='', after=None, limit=200, selected_index='', order=None):
        if mode != 'indices' or type(limit) is not int or not 1 <= limit <= 500 or not isinstance(search, str) or len(search) > 100:
            raise ValueError('指数目录查询范围无效')
        if selected_index:
            index_code(selected_index)
        def read(conn):
            params = dict(search='%' + search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%', selected=selected_index)
            return_page = ordered_page(conn, 'SELECT index_code,name AS index_name,native_market FROM yuanhang_index '
                'WHERE active=TRUE AND (name LIKE :search OR CONVERT(index_code USING utf8mb4) LIKE :search) '
                "AND (:selected='' OR index_code=:selected)", params,
                fields=column_fields(('index_code', 'index_name', 'native_market')), identity=('index_code',),
                order=order or {'field': 'index_code', 'direction': 'asc'}, after=after, limit=limit)
            return dict(rows=return_page[0], next=return_page[1])
        return await self.read(read)

    async def preparation_check(self, request=None):
        return await catalog_checks(self, PreparationScope.parse(request))

    async def stop(self):
        self.mysql = self.context = None

    def health(self):
        return {'status': 'ok' if getattr(self, 'mysql', None) else 'stopped'}


class MemberQuery(CatalogQuery):
    manifest = PluginManifest('data.yuanhang_index_members', '同花顺网页指数成分查询',
        requires=('mysql.store', 'yuanhang.indices.query'), provides=('indices.query',))
    preparation = (PreparationContribution('board_history', 'indices.query', '同花顺网页端', MEMBER_PROJECT,
        MEMBER_PROJECT + '-v1', MEMBER_DATASET, 'collector.yuanhang_index_members', TESTS, INTEGRATION, scoped=True),)

    async def start(self, context):
        self.context = context
        self.mysql, self.directory = context.get('mysql.store'), context.get('yuanhang.indices.query')
        await self.mysql.require_schema(member_dataset.TABLES, member_dataset.KEYS)
        return {'indices.query': self}

    async def catalog(self, codes=None):
        return await self.directory.catalog(codes)

    async def browse(self, mode='members', search='', after=None, limit=200, selected_index='', order=None):
        if type(limit) is not int or not 1 <= limit <= 500 or not isinstance(search, str) or len(search) > 100:
            raise ValueError('指数成分查询范围无效')
        if selected_index:
            index_code(selected_index)
        if mode not in ('indices', 'members'):
            raise ValueError('指数成分视图无效')
        def read(conn):
            if mode == 'members' and not search and (order is None or order == {'field': 'index_code', 'direction': 'asc'}):
                signature = digest(['members', selected_index, 'index_code', 'asc'])
                params, conditions = dict(limit=limit+1), ['i.active=TRUE', 's.available=TRUE']
                if selected_index:
                    conditions.append('m.index_code=:selected')
                    params['selected'] = selected_index
                if after is not None:
                    if (not isinstance(after, dict) or set(after) != {'query', 'keys'}
                            or after['query'] != signature or not isinstance(after['keys'], list) or len(after['keys']) != 2):
                        raise ValueError('成分游标不属于当前查询，请返回第一页')
                    index_code(after['keys'][0])
                    member_dataset.member_identity(after['keys'][1])
                    params.update(code=after['keys'][0], member=after['keys'][1])
                    conditions.append('(m.index_code>:code OR (m.index_code=:code AND m.source_code>:member))')
                rows = [dict(r) for r in conn.execute(text(
                    'SELECT i.index_code,i.name AS index_name,i.native_market,s.available AS members_available,'
                    's.member_count,m.source_code,m.unified_code,m.name FROM ths_index_member m FORCE INDEX (PRIMARY) '
                    'STRAIGHT_JOIN yuanhang_index i ON i.index_code=m.index_code '
                    'STRAIGHT_JOIN ths_index_member_state s ON s.index_code=m.index_code WHERE '
                    + ' AND '.join(conditions) + ' ORDER BY m.index_code,m.source_code LIMIT :limit'), params).mappings()]
                cursor = dict(query=signature, keys=[rows[limit-1]['index_code'],rows[limit-1]['source_code']]) if len(rows)>limit else None
                return dict(rows=rows[:limit], next=cursor)
            params = dict(search='%' + search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%', selected=selected_index)
            columns = 'i.index_code,i.name AS index_name,i.native_market,s.available AS members_available,s.member_count'
            sql = ' FROM yuanhang_index i LEFT JOIN ths_index_member_state s ON s.index_code=i.index_code'
            names = ('index_code', 'index_name', 'native_market', 'members_available', 'member_count')
            keys = ('index_code',)
            search_fields = '(i.name LIKE :search OR CONVERT(i.index_code USING utf8mb4) LIKE :search'
            if mode == 'members':
                columns += ',m.source_code,m.unified_code,m.name'
                sql += ' JOIN ths_index_member m ON m.index_code=i.index_code AND s.available=TRUE'
                names += ('source_code', 'unified_code', 'name')
                keys += ('source_code',)
                search_fields += (' OR m.name LIKE :search OR CONVERT(m.source_code USING utf8mb4) LIKE :search'
                                  ' OR CONVERT(m.unified_code USING utf8mb4) LIKE :search')
            search_fields += ')'
            if mode == 'members' and re.fullmatch(r'[0-9A-Z]{6}', search):
                params['exact'] = search
                sql = (' FROM (SELECT index_code,source_code FROM ths_index_member WHERE index_code=:exact '
                    'UNION SELECT index_code,source_code FROM ths_index_member WHERE source_code=:exact) hits '
                    'JOIN ths_index_member m ON m.index_code=hits.index_code AND m.source_code=hits.source_code '
                    'JOIN yuanhang_index i ON i.index_code=m.index_code '
                    'JOIN ths_index_member_state s ON s.index_code=i.index_code AND s.available=TRUE')
                search_fields = 'TRUE'
            elif mode == 'members' and re.fullmatch(r'[0-9]{6}\.(SH|SZ|BJ)', search):
                params['security'] = search
                search_fields = 'm.unified_code=:security'
            sql = 'SELECT ' + columns + sql + ' WHERE i.active=TRUE AND ' + search_fields + " AND (:selected='' OR i.index_code=:selected)"
            rows, cursor = ordered_page(conn, sql, params, fields=column_fields(names), identity=keys,
                order=order or {'field': 'index_code', 'direction': 'asc'}, after=after, limit=limit)
            return dict(rows=rows, next=cursor)
        return await self.read(read)

    async def preparation_check(self, request=None):
        return await member_checks(self, PreparationScope.parse(request))
