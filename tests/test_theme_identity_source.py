import pytest

from empire.sources.security_identity import parse_identity


def test_exact_original_code_not_replaced_by_related_new_code():
    body = (b'var themeIdentity="name,11,302132,sz302132,name,,name,99,1,,,name;'
            b'sz300114,11,300114,sz300114,old,,old,99,0,,,";')
    assert parse_identity(body, '300114') == '300114.SZ'
    with pytest.raises(ValueError):
        parse_identity(body, '300115')


@pytest.mark.parametrize('body', [
    b'var themeIdentity="name,11,302132,sz302132,name,,name,99,1,,,name";',
    b'var themeIdentity="name,11,300114,sh300115,name,,name,99,1,,,name";',
    b'var themeIdentity="name,12,300114,sz300114,name,,name,99,1,,,name";',
    b'var themeIdentity="name,11,300114,sz300114,name,,name,99,1,,,name;name,11,300114,sh300114,name,,name,99,1,,,name";',
    b'var themeIdentity=""; execute();',
])
def test_unknown_conflicting_or_truncated_identity_rejected(body):
    with pytest.raises(ValueError):
        parse_identity(body, '300114')


def test_stock_and_index_share_code_requires_exact_source_company_name():
    # Real failing code: 000016 also identifies the Shanghai 50 index.
    body = ('var themeIdentity="sh000016,11,000016,sh000016,上证50,,上证50,99,1,,,;'
            'sz000016,11,000016,sz000016,*ST康佳A,,*ST康佳A,99,0,ESG,,深康佳A";').encode('gb18030')
    assert parse_identity(body, '000016', source_name='*ST康佳A') == '000016.SZ'
    for label in (None, '未核实公司', '深康佳A'):
        with pytest.raises(ValueError, match='000016'):
            parse_identity(body, '000016', source_name=label)


def test_company_label_cannot_replace_original_code_or_resolve_same_name_conflict():
    body = b'var themeIdentity="x,11,302132,sz302132,old,,old,99,1,,,old";'
    with pytest.raises(ValueError):
        parse_identity(body, '300114', source_name='old')
    body = (b'var themeIdentity="x,11,300114,sz300114,old,,old,99,1,,,old;'
            b'x,11,300114,sh300114,old,,old,99,1,,,old";')
    with pytest.raises(ValueError):
        parse_identity(body, '300114', source_name='old')


def test_delisted_stock_thirteenth_auxiliary_field_keeps_exact_identity():
    # The observed 002711 lookup has 13 fields; the identity prefix is unchanged.
    body = ('var themeIdentity="sz002711,11,002711,sz002711,欧浦退,'
            ',欧浦退,99,0,,,欧浦智网,";').encode('gb18030')
    assert parse_identity(body, '002711', source_name='*ST欧浦') == '002711.SZ'
    with pytest.raises(ValueError):
        parse_identity(body, '002712')


@pytest.mark.parametrize('width', [5, 11, 14])
def test_unknown_identity_field_layout_stays_rejected(width):
    fields = [b'sz002711', b'11', b'002711', b'sz002711', b'name'] + [b''] * (width - 5)
    with pytest.raises(ValueError, match='字段改变'):
        parse_identity(b'var themeIdentity="' + b','.join(fields) + b'";', '002711')
