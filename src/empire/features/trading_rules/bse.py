"""Complete Beijing directory and explicit deferred-clause checks."""
import json

from empire.features.trading_rules.documents import compact, html_document

BJ_LIST = 'https://www.bse.cn/info/listseSub.do'
BJ_NOTICE = 'https://www.bse.cn/jygl_list/200028217.html'
BJ_RESUMED = 'https://www.bse.cn/jygl_list/200029608.html'
BJ_FILE = 'https://www.bse.cn/uploads/6/file/public/202604/20260424170528_52kqyhc7p9.docx'
BJ_FIELDS = ['infoId', 'title', 'htmlUrl', 'metaDescription', 'subTitle', 'fileUrl', 'fileName',
             'linkUrl', 'mlinkUrl', 'picURL', 'nodeId', 'p1', 'potenctLevel', 'publishDate']


def directory(body):
    raw = body.decode('utf-8')
    if not raw.startswith('null(') or not raw.endswith(')'):
        raise ValueError('北交所规则目录包装无效')
    response = json.loads(raw[5:-1])
    if not isinstance(response, list) or len(response) != 1 or response[0].get('result') is not True:
        raise ValueError('北交所规则目录响应无效')
    data = response[0]['data']
    rows = data['content']
    if data.get('number') != 0 or not data.get('lastPage') or data.get('totalElements') != len(rows) or not 1 <= len(rows) <= 100:
        raise ValueError('北交所规则目录完整集合变化或未收齐')
    if len({r['infoId'] for r in rows}) != len(rows) or any(r.get('nodeId') != 1304 for r in rows):
        raise ValueError('北交所规则目录重复或栏目不符')
    relevant = {r['infoId']: r for r in rows if '交易规则' in r['title']}
    if set(relevant) != {200028217, 200029608} or relevant[200028217]['fileUrl'] != BJ_FILE.removeprefix('https://www.bse.cn'):
        raise ValueError('北交所交易规则或施行公告变化，须重新审核')


def notice(body, resumed=False):
    text, _ = html_document(body)
    full = compact(text)
    require = ('北证公告〔2026〕43号', '2026年8月31日起实施', '第4.5.1条至第4.5.4条',
        '第3.6.5条第二款和第三款关于无价格涨跌幅限制股票的大宗交易申报价格范围的规定，自2026年10月26日起正式实施。',
        '2026-10-16', '现行有效') if resumed else (
        '17号', '2026年7月6日', '第3.6.5条第二款和第三款', '第3.7.1条至第3.7.10条',
        '第4.5.1条至第4.5.4条', '另行通知', '现行有效')
    if any(x not in full for x in require) or (resumed and '3.7.' in full):
        raise ValueError('北交所生效或暂缓条款变化，须重新审核')
