"""Complete expected-unit/content checks through the existing formal queries."""
from sqlalchemy import text

from empire.contracts.data import make_envelope


async def verify_queries(args, manager, worker, expected_units):
    if args.dataset == 'mixed':
        from types import SimpleNamespace
        groups = {}
        for dataset, name in (('financial', 'income.statement'), ('capital', 'ths.capital.security')):
            subset = {key: value for key, value in expected_units.items() if value['dataset'] == name}
            groups[dataset] = await verify_queries(SimpleNamespace(dataset=dataset), manager, worker, subset)
        return dict(groups=groups, extra_business_keys=False)
    plugin = {'calendar': 'data.trade_calendar', 'financial': 'data.income',
              'capital': 'data.ths_capital'}[args.dataset]
    await manager.start(plugin)
    query = manager.entries[plugin].plugin
    checked = records = 0
    for template in expected_units.values():
        expected = worker.catalog.normalize(make_envelope(**template, run_id='verify', batch_id='verify'))['rows']
        if args.dataset == 'calendar':
            actual = await query.month(template['payload']['month'])
            assert [{k: r[k] for k in ('trade_date', 'is_trade')} for r in actual['rows']] == expected
            records += len(expected)
        elif args.dataset == 'financial':
            actual = await query.list_statements(template['business_key'].split(':')[1], limit=500)
            assert actual == expected, template['business_key']
            records += len(expected)
        else:
            from empire.features.ths_capital.contract import TABLE_SECTIONS
            for table, sections in TABLE_SECTIONS.items():
                actual = {}
                for section in sections:
                    cursor = None
                    while True:
                        page = await query.browse(table, section, code=template['business_key'], after=cursor, limit=100)
                        for row in page['rows']:
                            detail = await query.detail(table, row['record_key'])
                            actual[row['record_key']] = {name: detail[name] for name in expected[table][0]}
                        cursor = page['next']
                        if cursor is None:
                            break
                assert actual == {row['record_key']: row for row in expected[table]}, (template['business_key'], table)
                records += len(expected[table])
        checked += 1
    mysql = manager.registry.get('mysql.store')

    def all_keys():
        with mysql.read_engine.connect() as conn:
            if args.dataset == 'calendar':
                actual = set(conn.execute(text("SELECT DISTINCT DATE_FORMAT(trade_date,'%Y-%m') "
                                               "FROM trade_calendar")).scalars())
                assert actual == {t['business_key'] for t in expected_units.values()}
            elif args.dataset == 'financial':
                actual = set(conn.execute(text('SELECT DISTINCT unified_code FROM income_statement')).scalars())
                expected = {t['business_key'][3:] + '.' + t['business_key'][:2]
                            for t in expected_units.values()}
                assert actual == expected
            else:
                from empire.features.ths_capital.contract import TABLE_SECTIONS
                for table in TABLE_SECTIONS:
                    actual = set(conn.execute(text(f'SELECT DISTINCT unified_code FROM {table}')).scalars())
                    expected = {t['business_key'] for t in expected_units.values()}
                    assert actual == expected, table
    await mysql.read(all_keys)
    return dict(units=checked, records=records, extra_business_keys=False,
                scope='all seeded/new/revised units, complete content via formal queries; complete SQL unit set')
