"""Bounded identity candidates from current and project-specific archived data."""
from sqlalchemy import text

TABLES = {
    'stock': ('stock', 'name'), 'listings': ('stock_listing', None),
    'dividends': ('dividend_plan', 'name'), 'additional_issues': ('additional_issue', 'name'),
    'rights_issues': ('rights_issue', 'name'), 'suspensions': ('suspension_event', 'name'),
    'listing_status': ('security_listing_event', 'name'),
    'names_company': ('security_name_change', 'new_name'),
    'names_security': ('security_name_change', 'new_name'),
    'st_implementation': ('security_st_event', 'new_name'),
    'st_removal': ('security_st_event', 'new_name'),
    'income': ('income_statement', None), 'balance': ('balance_statement', None),
    'cashflow': ('cashflow_statement', None),
}


async def candidates(mysql, search='', dataset='stock', limit=20):
    if not isinstance(search, str) or len(search) > 100 or type(limit) is not int or not 1 <= limit <= 30:
        raise ValueError('证券候选范围无效')
    if dataset not in TABLES:
        raise ValueError('未登记的证券候选数据集')
    table, name = TABLES[dataset]
    name_expr = f'COALESCE(s.name,b.{name},b.unified_code)' if name else 'COALESCE(s.name,b.unified_code)'
    pattern = '%' + search.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    clauses = ['(CONVERT(b.unified_code USING utf8mb4) LIKE :search OR s.name LIKE :search'
               + (f' OR b.{name} LIKE :search' if name else '')
               + (' OR b.old_name LIKE :search' if 'names_' in dataset or dataset.startswith('st_') else '') + ')']
    params = dict(search=pattern, limit=limit)
    if dataset.startswith('names_') or dataset.startswith('st_'):
        field = 'name_kind' if dataset.startswith('names_') else 'event_kind'
        clauses.append(f'b.{field}=:kind')
        params['kind'] = dataset.split('_', 1)[1]
    def read():
        with mysql.read_engine.connect() as conn:
            rows = conn.execute(text(f'SELECT DISTINCT b.unified_code,{name_expr} AS name '
                f'FROM {table} b LEFT JOIN stock s ON s.unified_code=b.unified_code '
                f'WHERE {" AND ".join(clauses)} ORDER BY b.unified_code,name LIMIT :limit'), params).mappings()
            return [dict(r) for r in rows]
    return await mysql.read(read)
