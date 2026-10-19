"""Public pure source protocol extracted without business-rule changes."""
from empire.features.capital_actions.fields import TdxSourceError

PAGE_URL = 'http://page2.tdx.com.cn:7615/site/tdxsj/html/tdxsj_zfsp_zfsp.html'


DETAIL_URL = 'http://page2.tdx.com.cn:7615/site/tdxsj/html/tdxsj_zfsp_zfspmx.html'


ENTRIES = {'dividends': 'tdxsj_zfsp_zfsp', 'additional_issues': 'tdxsj_xgzx_zf',
           'rights_issues': 'tdxsj_xgzx_pg'}


def result_set(body, index, columns):
    if isinstance(body, dict) and type(body.get('ErrorCode')) is int and body['ErrorCode'] != 0:
        raise TdxSourceError(body['ErrorCode'], '通达信增发送配')
    if not isinstance(body, dict) or body.get('ErrorCode') != 0:
        raise ValueError('通达信增发送配请求失败')
    sets = body.get('ResultSets')
    if not isinstance(sets, list) or len(sets) != 3:
        raise ValueError('通达信增发送配结果集缺失')
    value = sets[index]
    if not isinstance(value, dict) or value.get('ColName') != columns or not isinstance(value.get('Content'), list):
        raise ValueError('通达信增发送配列结构不匹配')
    rows = value['Content']
    if type(value.get('Count')) is not int or value['Count'] != len(rows):
        raise ValueError('通达信增发送配结果条数不符')
    if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
        raise ValueError('通达信增发送配行结构无效')
    return rows


URL = 'http://page2.tdx.com.cn:7615/TQLEX?Entry=CWServ.tdxsj_xgzx_zfmx'
