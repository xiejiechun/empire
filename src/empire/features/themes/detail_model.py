"""Normalize source detail identities and cross-check its two association views.

Source stock codes remain source identities. Formal SQL integration must resolve
them through the shared security mapping, never guess markets from prefixes here.
"""
import re


class DetailError(ValueError):
    """Missing, masked or inconsistent details cannot replace an existing version."""


def source_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,32}', value):
        raise DetailError('题材或分类来源ID非法')
    return value


def _text(value, *, limit=128, required=False):
    if not isinstance(value, str) or len(value.encode('utf-8')) > limit or '\x00' in value:
        raise DetailError('详情文本类型错误或超限')
    if required and (not value.strip() or '***' in value):
        raise DetailError('详情必需文本为空或被掩码')
    return value


def _number(value):
    if type(value) is int:
        number = value
    elif isinstance(value, str) and re.fullmatch(r'[0-9]{1,12}', value):
        number = int(value)
    else:
        raise DetailError('详情整数无效')
    if not 0 <= number <= 999999999999:
        raise DetailError('详情整数超界')
    return number


def _list(value, limit):
    if not isinstance(value, list) or len(value) > limit:
        raise DetailError('详情数组类型错误或超限')
    return value


def _mapping(value, required, allowed):
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - allowed:
        raise DetailError('详情字段缺失或来源结构改变')
    return value


def _stock_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{6}', value):
        raise DetailError('证券来源代码必须为六位数字')
    return value


TOP = {'ID', 'Name', 'BriefIntro', 'Introduction', 'CreateTime', 'UpdateTime',
       'Table', 'Stocks', 'StockList', 'errcode'}
TOP_ALLOWED = TOP | {'ClassLayer', 'Desc', 'PlateSwitch', 'StkSwitch', 'IsNew', 'ZT',
                     'Power', 'Subscribe', 'IsGood', 'ComNum', 'GoodNum', 't'}
CATEGORY = {'ID', 'Name', 'ZSCode', 'FirstShelveTime', 'UpdateCacheTime', 'IsNew', 'Stocks'}
RELATION = {'StockID', 'prod_name', 'Reason', 'IsZz', 'IsHot', 'FirstShelveTime',
            'UpdateCacheTime', 'IsNew', 'Hot'}


def parse_detail(payload, requested_id):
    """Known Level1/Level2 structure; new structures fail instead of losing rows.

    Cross-check StockList.Tag against Table associations by category/code/reason,
    not merely stock counts. Live whole-directory coverage is a separate proof.
    """
    source_id(requested_id)
    _mapping(payload, TOP, TOP_ALLOWED)
    if type(payload['errcode']) not in (str, int) or str(payload['errcode']) != '0':
        raise DetailError('详情接口未成功')
    if source_id(payload['ID']) != requested_id:
        raise DetailError('响应题材ID与请求不符')
    if payload['Stocks'] != []:
        raise DetailError('来源出现未核实的无分类Stocks，拒绝遗漏归档')
    result = {'theme_id': requested_id, 'name': _text(payload['Name'], required=True),
              'brief': _text(payload['BriefIntro'], limit=65536),
              'introduction': _text(payload['Introduction'], limit=1024 * 1024),
              'source_created_at': _number(payload['CreateTime']) or None,
              'source_updated_at': _number(payload['UpdateTime']) or None,
              'categories': [], 'stocks': [], 'relations': []}
    categories, expected, names = {}, {}, {}

    def category(raw, parent):
        _mapping(raw, CATEGORY, CATEGORY)
        cid = source_id(raw['ID'])
        if cid in categories:
            raise DetailError('详情分类ID重复')
        record = {'category_id': cid, 'parent_id': parent,
                  'name': _text(raw['Name'], required=True), 'order': len(categories),
                  'plate_code': _text(raw['ZSCode'], limit=32),
                  'first_shelved_at': _number(raw['FirstShelveTime']) or None,
                  'updated_at': _number(raw['UpdateCacheTime']) or None,
                  'is_new': _number(raw['IsNew'])}
        categories[cid] = record
        if len(categories) > 5000:
            raise DetailError('详情分类数量超限')
        for stock in _list(raw['Stocks'], 10000):
            _mapping(stock, RELATION, RELATION)
            code = _stock_id(stock['StockID'])
            name = _text(stock['prod_name'], required=True)
            if code in names and names[code] != name:
                raise DetailError('同一证券来源名称冲突')
            names[code] = name
            identity = cid, code
            if identity in expected:
                raise DetailError('分类内证券关联重复')
            reason = _text(stock['Reason'], limit=65536, required=True)
            expected[identity] = reason
            result['relations'].append({'category_id': cid, 'source_stock_id': code,
                'reason': reason, 'first_shelved_at': _number(stock['FirstShelveTime']) or None,
                'updated_at': _number(stock['UpdateCacheTime']) or None,
                'is_new': _number(stock['IsNew']), 'is_hot': _number(stock['IsHot']),
                'source_is_zz': _number(stock['IsZz'])})
            if len(expected) > 50000:
                raise DetailError('详情关联数量超限')
        return cid

    for group in _list(payload['Table'], 5000):
        _mapping(group, {'Level1'}, {'Level1', 'Level2'})
        parent = category(group['Level1'], None)
        for child in _list(group.get('Level2', []), 5000):
            category(child, parent)
    actual, codes = {}, set()
    for stock in _list(payload['StockList'], 10000):
        _mapping(stock, {'StockID', 'prod_name', 'Tag'}, {'StockID', 'prod_name', 'Tag', 'HotNum'})
        code = _stock_id(stock['StockID'])
        if code in codes:
            raise DetailError('股票总表代码重复')
        codes.add(code)
        name = _text(stock['prod_name'], required=True)
        if names.get(code) != name:
            raise DetailError('股票总表与分类证券名称或集合不符')
        result['stocks'].append({'source_stock_id': code, 'name': name})
        for tag in _list(stock['Tag'], 5000):
            _mapping(tag, {'ID', 'Name', 'Reason'}, {'ID', 'Name', 'Reason'})
            cid = source_id(tag['ID'])
            identity = cid, code
            if identity in actual or cid not in categories:
                raise DetailError('股票标签重复或分类身份未知')
            if _text(tag['Name'], required=True) != categories[cid]['name']:
                raise DetailError('股票标签与分类名称不符')
            actual[identity] = _text(tag['Reason'], limit=65536, required=True)
    if codes != set(names) or actual != expected:
        raise DetailError('股票总表标签与分类关联集合或理由不一致')
    result['categories'] = list(categories.values())
    return result
