import pytest

from scripts.inspect_yuanhang_protocol import resource_dictionary


def test_market_dictionary_preserves_beijing_and_new_third_board_distinction():
    data = b'''<Markets>
      <Market id="USTA" old_id="145"><Name zh-cn="NEEQ"/></Market>
      <Market id="USTM" old_id="151"><Name zh-cn="Beijing A"/></Market>
      <Market id="UNQQ"><Name zh-cn="unrelated"/></Market>
    </Markets>'''
    result = resource_dictionary('Hevo.Core.DataModel.Data.MarketData.xml', data)
    assert [(row['attributes']['id'], row['attributes']['old_id'])
            for row in result['entries']] == [('USTA', '145'), ('USTM', '151')]


def test_unknown_resources_are_not_parsed_or_exposed():
    assert resource_dictionary('UserRecordHistory.xml', b'private') is None


@pytest.mark.parametrize('data', [b'', b'x' * 1048577,
    b'<!DOCTYPE x [<!ENTITY a "data">]><x/>'], ids=['empty', 'oversized', 'entity'])
def test_dictionary_size_and_entity_declarations_rejected(data):
    with pytest.raises(ValueError, match='dictionary'):
        resource_dictionary('Hevo.Core.DataModel.Data.QuoteFieldData.xml', data)
