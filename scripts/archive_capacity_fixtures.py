"""Deterministic synthetic complete units; never downloaded from public sites."""
import hashlib
import json


def fixture(dataset, index, *, revision=False, large=False, source_only=False):
    if dataset == 'mixed':
        return fixture(('financial', 'capital')[index % 2], index // 2,
                       revision=revision, large=large, source_only=source_only)
    code = f'{600000 + index:06d}'
    if dataset == 'calendar':
        from empire.features.calendar.contract import month_dates
        month = f'{1991 + index // 12:04d}-{index % 12 + 1:02d}'
        return dict(source='cninfo', dataset='calendar.month', job_key='cninfo-calendar-v1',
            schema_version=1, business_key=month, payload=dict(page=1, month=month,
                rows=[dict(trade_date=day.isoformat(), is_trade=bool((i + revision) % 2))
                      for i, day in enumerate(month_dates(month))]))
    if dataset == 'financial':
        from empire.features.financial_statements.contract import parse
        from empire.features.financial_statements.wire import pack_rows
        from tests.test_ths_statements import large_source, source
        body = large_source('income') if large else source('income', '2.00亿' if revision else '1.00亿')
        matrix = json.loads(body['flashData'])
        if not large:
            dates = [f'{2025 - i // 4}-{("12-31", "09-30", "06-30", "03-31")[i % 4]}' for i in range(100)]
            matrix['report'] = [dates] + [[values[0]] * 100 for values in matrix['report'][1:]]
            for extra in range(3):
                title = list(matrix['title'][1])
                title[0] = f'容量扩展科目{extra}'
                matrix['title'].append(title)
                matrix['report'].append(['1.00亿'] * 100)
        else:
            dates = [f'{2025 - i // 4}-{("12-31", "09-30", "06-30", "03-31")[i % 4]}' for i in range(300)]
            matrix['title'] = matrix['title'][:65]
            matrix['report'] = [dates] + [[values[0]] * 300 for values in matrix['report'][1:65]]
            if revision:
                matrix['report'][1][0] = '2.00亿'
        body['flashData'] = json.dumps(matrix)
        stock = dict(market='SH', code=code, name='合成容量样本')
        if source_only:
            return body, stock
        rows = parse('income', body, stock)
        return dict(source='ths', dataset='income.statement', job_key='ths-income-v1',
            schema_version=2, business_key='SH:' + code, payload=dict(page=1, unit='SH:' + code,
                rows=pack_rows(rows), manifest=None))
    from empire.features.ths_capital.source import parse
    from empire.features.ths_capital.transport import pack
    from tests.test_ths_capital import source, table
    # Independent deterministic prose tokens avoid an unrealistically tiny
    # compression ratio from repeating one padding string in every record.
    projects = [('2025-01-01', f'项目{i:04d}', '2.00亿' if revision else '1.00亿', '0.00', '3.5', '-2%', '-',
                 '<a class="progressView" content="Synthetic capacity project ' +
                 ' '.join(hashlib.sha256(f'{index}:{i}:{j}'.encode()).hexdigest()
                          for j in range(8 if large else 2)) +
                 (hashlib.sha256(f'{index}:{i}:tail'.encode()).hexdigest()[:16] if large else '') + '">展开</a>')
                for i in range(987 if large else 87)]
    html = source().replace('601139', code)
    start = html.index('<table>', html.index('id="progress"'))
    end = html.index('</table>', start) + len('</table>')
    html = html[:start] + table('capital_project', projects) + html[end:]
    unit = code + '.SH'
    body, stock = html.encode('gb18030'), dict(code=code, unified_code=unit, name='合成容量样本')
    if source_only:
        return body, stock
    data = parse(body, stock)
    return dict(source='ths', dataset='ths.capital.security', job_key='ths-capital-v1',
        schema_version=2, business_key=unit, payload=dict(page=1, unit=unit,
            rows=pack(data['rows']), availability=data['availability'], manifest=None))
