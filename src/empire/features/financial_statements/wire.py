"""Schema 2: lossless matrix transport without repeating labels for each report."""
SCHEMA_VERSION = 2
COMMON = {'market', 'code', 'name', 'basis', 'currency', 'period_basis', 'announcement_date'}


def pack_rows(rows):
    if not rows:
        return []  # Only the final round manifest has no statement matrix.
    common = {k: rows[0][k] for k in COMMON}
    columns = sorted(rows[0]['fields'])
    reports = []
    for row in rows:
        if {k: row[k] for k in COMMON} != common or sorted(row['fields']) != columns:
            raise ValueError('财报矩阵证券信息或科目集合不一致')
        reports.append([row['report_date'], [None if row['fields'][k] is None else
                        [row['fields'][k]['value'], row['fields'][k]['resolution']] for k in columns]])
    return dict(common=common, columns=columns, reports=reports)


def unpack_rows(matrix):
    if (not isinstance(matrix, dict) or set(matrix) != {'common', 'columns', 'reports'}
            or not isinstance(matrix['common'], dict) or set(matrix['common']) != COMMON):
        raise ValueError('财报传输矩阵结构无效')
    columns, reports = matrix['columns'], matrix['reports']
    if (not isinstance(columns, list) or not 1 <= len(columns) <= 400
            or any(not isinstance(c, str) or not 1 <= len(c) <= 200 for c in columns)
            or columns != sorted(set(columns))
            or not isinstance(reports, list) or not 1 <= len(reports) <= 300):
        raise ValueError('财报传输矩阵科目或期间无效')
    rows = []
    for report in reports:
        if (not isinstance(report, list) or len(report) != 2 or not isinstance(report[1], list)
                or len(report[1]) != len(columns)):
            raise ValueError('财报传输矩阵缺列')
        values = {}
        for key, value in zip(columns, report[1], strict=True):
            if value is not None and (not isinstance(value, list) or len(value) != 2
                    or any(not isinstance(v, str) or len(v) > 80 for v in value)):
                raise ValueError('财报传输金额或精度无效')
            values[key] = None if value is None else dict(value=value[0], resolution=value[1])
        rows.append({**matrix['common'], 'report_date': report[0], 'fields': values})
    return rows
