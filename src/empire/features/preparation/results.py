"""Separate collection proof, quality findings and declared-use readiness."""
DIMENSIONS = {'开发验收': 'development', '采集完整性': 'integrity', '来源质量': 'quality', '用途条件': 'usage'}


def dimension(item):
    if item['phase'] == '开发':
        return '开发验收'
    if item['id'] in ('keys', 'coverage'):
        return '采集完整性'
    if item['id'] in ('fields', 'quality'):
        return '来源质量'
    return '用途条件'


def accepted(item):
    return item['status'] == 'pass' or not item.get('blocking', True)


def summarize(checks):
    result = {}
    for title, key in DIMENSIONS.items():
        selected = [c for c in checks if dimension(c) == title]
        if not selected or any(c['status'] == 'unknown' and c.get('blocking', True) for c in selected):
            state = '未确认'
        elif any(not accepted(c) for c in selected):
            state = '未通过' if key == 'development' else '有缺口' if key == 'integrity' else '有异常' if key == 'quality' else '不满足'
        elif any(not c.get('blocking', True) for c in selected):
            state = '有限制'
        else:
            state = '通过'
        result[key] = state
    data = [c for c in checks if c['phase'] == '数据']
    result['usable'] = bool(data) and all(accepted(c) for c in data)
    result['use_state'] = ('可用（有限制）' if any(not c.get('blocking', True) for c in data) else '可用') if result['usable'] else (
        '不可用' if any(c['status'] == 'fail' and c.get('blocking', True) for c in data) else '未确认')
    if result['integrity'] != '通过' and result['quality'] == '通过':
        result['quality'] = '已查部分通过'
    blocking = [c for c in data if c['status'] != 'pass' and c.get('blocking', True)]
    result['outcome'] = ('检查失败' if any(c.get('reason') == 'query_error' for c in blocking) else
                         '未检查' if not data or any(c['status'] == 'unknown' for c in blocking) else
                         '检查失败' if any(c.get('reason') != 'source_limit' for c in blocking) else
                         '来源受限' if blocking else '通过')
    return result
