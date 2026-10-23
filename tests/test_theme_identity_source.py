import pytest

from empire.features.themes.detail_model import DetailError
from empire.features.themes.identity_source import parse_identity


def test_exact_original_code_not_replaced_by_related_new_code():
    body = (b'var themeIdentity="name,11,302132,sz302132,name,,name,99,1,,,name;'
            b'sz300114,11,300114,sz300114,old,,old,99,0,,,";')
    assert parse_identity(body, '300114') == '300114.SZ'
    with pytest.raises(DetailError):
        parse_identity(body, '300115')


@pytest.mark.parametrize('body', [
    b'var themeIdentity="name,11,302132,sz302132,name,,name,99,1,,,name";',
    b'var themeIdentity="name,11,300114,sh300115,name,,name,99,1,,,name";',
    b'var themeIdentity="name,12,300114,sz300114,name,,name,99,1,,,name";',
    b'var themeIdentity="name,11,300114,sz300114,name,,name,99,1,,,name;name,11,300114,sh300114,name,,name,99,1,,,name";',
    b'var themeIdentity=""; execute();',
])
def test_unknown_conflicting_or_truncated_identity_rejected(body):
    with pytest.raises(DetailError):
        parse_identity(body, '300114')
