from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from empire.features.themes.detail_model import DetailError, parse_detail
from empire.features.themes.detail_source import fetch_detail, request_options
from empire.plugins.infra.http import HttpService


def sample():
    stock = {'StockID': '600001', 'prod_name': '示例股份', 'Reason': '来源说明',
             'IsZz': '2', 'IsHot': '0', 'FirstShelveTime': '1703489277',
             'UpdateCacheTime': '0', 'IsNew': 0, 'Hot': 100}
    category = {'ID': '7', 'Name': '示例分类', 'ZSCode': '0',
                'FirstShelveTime': '1703489277', 'UpdateCacheTime': '0',
                'IsNew': 0, 'Stocks': [stock]}
    return {'ID': '148', 'Name': '示例题材', 'BriefIntro': '简介', 'Introduction': '<p>正文</p>',
            'CreateTime': '1703489277', 'UpdateTime': '1790072615', 'Table': [{'Level1': category}],
            'Stocks': [], 'StockList': [{'StockID': '600001', 'prod_name': '示例股份',
                                       'Tag': [{'ID': '7', 'Name': '示例分类', 'Reason': '来源说明'}]}],
            'errcode': '0', 'Power': 0}


def test_detail_preserves_business_text_and_source_identity_without_market_guess():
    original = sample()
    before = deepcopy(original)
    parsed = parse_detail(original, '148')
    assert original == before
    assert parsed['introduction'] == '<p>正文</p>'
    assert parsed['categories'][0]['updated_at'] is None
    assert parsed['stocks'] == [{'source_stock_id': '600001', 'name': '示例股份'}]
    assert parsed['relations'][0]['reason'] == '来源说明'
    assert 'Power' not in parsed  # Power=0 is not proof of a masked payload.


def test_same_stock_in_different_categories_preserves_both_reasons():
    value = sample()
    child = deepcopy(value['Table'][0]['Level1'])
    child.update(ID='8', Name='子分类')
    child['Stocks'][0]['Reason'] = '另一个理由'
    value['Table'][0]['Level2'] = [child]
    value['StockList'][0]['Tag'].append({'ID': '8', 'Name': '子分类', 'Reason': '另一个理由'})
    result = parse_detail(value, '148')
    assert len(result['stocks']) == 1 and len(result['relations']) == 2
    assert result['categories'][1]['parent_id'] == '7'


@pytest.mark.parametrize('mutation', [
    lambda v: v.update(ID='229'),
    lambda v: v.update(errcode=True),
    lambda v: v.update(errcode='9999'),
    lambda v: v.update(Stocks=[{}]),
    lambda v: v.update(UnknownBusiness=[]),
    lambda v: v['StockList'].append(deepcopy(v['StockList'][0])),
    lambda v: v['Table'].append(deepcopy(v['Table'][0])),
    lambda v: v['Table'][0].update(Level3=[]),
    lambda v: v['Table'][0]['Level1']['Stocks'].append(deepcopy(v['Table'][0]['Level1']['Stocks'][0])),
    lambda v: v['StockList'][0]['Tag'].append(deepcopy(v['StockList'][0]['Tag'][0])),
    lambda v: v['StockList'][0]['Tag'][0].update(ID='8'),
    lambda v: v['StockList'][0]['Tag'][0].update(Reason='同条数但内容不同'),
    lambda v: v['StockList'][0]['Tag'][0].update(Name='不同分类名'),
    lambda v: v['StockList'][0].update(StockID='600002'),
    lambda v: v['StockList'][0].update(prod_name='***'),
    lambda v: v['StockList'][0].update(Tag=[]),
    lambda v: v['Table'][0]['Level1']['Stocks'][0].update(Reason=''),
    lambda v: v.update(CreateTime=-1),
])
def test_invalid_or_same_count_different_associations_are_rejected(mutation):
    value = sample()
    mutation(value)
    with pytest.raises(DetailError):
        parse_detail(value, '148')


def test_anonymous_request_cannot_accept_account_fields():
    a, b = request_options('148'), request_options('148')
    assert a['data']['DeviceID'] != b['data']['DeviceID']
    assert 'headers' not in a
    assert not {'Token', 'UserID', 'Cookie'} & a['data'].keys()
    with pytest.raises(DetailError):
        request_options('148&Token=x')


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid', [False, True])
async def test_shared_response_closed_after_parse_success_or_failure(invalid):
    response = Mock()
    data = sample()
    if invalid:
        data['ID'] = '229'
    response.json.return_value = data
    http = Mock(request=AsyncMock(return_value=response))
    if invalid:
        with pytest.raises(DetailError):
            await fetch_detail(http, '148', project_id='test-theme')
    else:
        result = await fetch_detail(http, '148', project_id='test-theme')
        assert result['theme_id'] == '148'
    response.close.assert_called_once()
    http.request.assert_awaited_once()
    options = http.request.await_args.kwargs
    assert options['max_redirects'] == 0
    assert options['allowed_domains'] == ('longhuvip.com',)
    assert options['strip_credentials'] is True


@pytest.mark.asyncio
async def test_actual_shared_transport_strips_inherited_credentials():
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(200, json=sample())

    service = HttpService(Mock(eval=AsyncMock(return_value=0)), 'test-theme', {},
                          transport=httpx.MockTransport(respond))
    service.client.cookies.set('session', 'synthetic-cookie', domain='applhb.longhuvip.com')
    service.client.headers['Authorization'] = 'Bearer synthetic-token'
    try:
        await fetch_detail(service, '148', project_id='test-theme')
        assert len(seen) == 1
        assert not {'cookie', 'authorization', 'proxy-authorization'} & seen[0].headers.keys()
        assert b'Token=' not in seen[0].content and b'UserID=' not in seen[0].content
        assert service.buffer_budget.used == 0
    finally:
        await service.close()
