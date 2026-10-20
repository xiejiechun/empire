"""Shared TDX unlock wire protocol; business interpretation remains in its owner."""
import json

PAGE = 'http://page2.tdx.com.cn:7615/site/tdxsj/html/tdxsj_cgbd_cgbd.html'

def body(params):
    return json.dumps({'Params': params}, separators=(',', ':')).encode()

def results(value, columns):
    if not isinstance(value, dict) or type(value.get('ErrorCode')) is not int or value['ErrorCode'] != 0:
        raise ValueError('大小非解禁来源返回错误')
    sets = value.get('ResultSets')
    if not isinstance(sets, list) or len(sets) != len(columns):
        raise ValueError('大小非解禁结果集缺失')
    output = []
    for s, cols in zip(sets, columns, strict=True):
        rows = s.get('Content')
        if (s.get('ColName') != cols or not isinstance(rows, list)
                or type(s.get('Count')) is not int or s['Count'] != len(rows)
                or any(not isinstance(r, list) or len(r) != len(cols) for r in rows)):
            raise ValueError('大小非解禁列或响应条数错误')
        output.append(rows)
    return output
