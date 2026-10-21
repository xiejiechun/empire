"""The same human-readable nominal distribution result in preparation and browsing."""


def distribution_text(result):
    scope = result['scope']
    lines = [f"{result['title']} · {result['state']}",
        f"证券：{'、'.join(scope['codes'])}；闭区间除息日：{scope['start']} ～ {scope['end']}；用途：{result['purpose']}",
        f"单位：{result['unit']}；币种：{result['currency']}",
        '实际证据时间：' + (result['observed_at'] or '缺少'),
        '本次检查时间：' + result['checked_at'], result['formula']]
    if result.get('problem'):
        lines.append('阻断：' + result['problem'])
    for security in result['securities']:
        lines.append(f"{security['security']}：{len(security['rows'])}笔；合计 {security['cash_per_share']} 元/股，"
                     f"{security['cash_per_ten']} 元/10股；完整单元{security['full_unit_count']}条")
        for row in security['rows']:
            lines.append(f"除息日 {row['ex_date']} · 报告期 {row['report_date']} · {row['status']} · "
                         f"{row['cash_per_share']} 元/股；业务键 {row['record_key']}")
    lines.extend('限制：' + limitation for limitation in result['limitations'])
    return '\n'.join(lines)
