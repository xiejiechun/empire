import base64
from xml.etree import ElementTree

import pytest

from empire.sources.yuanhang_identity import (
    decode_guest_history,
    history_filename,
    read_guest,
    require_local_probe,
)


def encoded_history(accounts, active='thsguest_fixture'):
    root = ElementTree.Element('UserRecordHistory', ActiveUser=active)
    for name, password in accounts:
        ElementTree.SubElement(root, 'UserRecord', InputedUserName=name,
            SavedPassword=base64.b64encode(password.encode()).decode())
    normal = b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
    custom = b'oPbsG4EvU8gyd02B3q6fIVWXYZaCcMeTKhxnwzmjApRrDtuHkiLlN1O9F5S7JQ+/'
    return base64.b64encode(ElementTree.tostring(root)).translate(bytes.maketrans(normal, custom))


def test_saved_guest_decodes_both_layers_without_exporting_secret():
    identity = decode_guest_history(encoded_history([('thsguest_fixture', 'test-secret')]))
    assert identity.account == 'thsguest_fixture'
    assert identity.password == 'test-secret'
    assert repr(identity) == 'GuestIdentity()'


@pytest.mark.parametrize('accounts,active', [
    ([('personal', 'secret')], 'personal'),
    ([('thsguest_fixture', 'secret')], 'personal'),
    ([('thsguest_fixture', 'secret'), ('thsguest_another', 'secret')], ''),
    ([('thsguest_fixture', '')], 'thsguest_fixture'),
])
def test_missing_or_ambiguous_guest_never_uses_personal_account(accounts, active):
    with pytest.raises(ValueError, match='unavailable') as error:
        decode_guest_history(encoded_history(accounts, active))
    assert 'secret' not in str(error.value)


def test_restart_reads_same_identity_without_mutating_client(tmp_path):
    folder = tmp_path / 'HeUsr'
    folder.mkdir()
    path = folder / history_filename(r'D:\Client\bin')
    content = encoded_history([('thsguest_fixture', 'test-secret')])
    path.write_bytes(content)
    assert read_guest(r'D:\Client\bin', tmp_path) == read_guest(r'D:\Client\bin', tmp_path)
    assert path.read_bytes() == content
    assert list(folder.iterdir()) == [path]


def test_missing_new_format_does_not_search_other_accounts(tmp_path):
    with pytest.raises(ValueError, match='history is unavailable'):
        read_guest(r'D:\Client\bin', tmp_path)


@pytest.mark.parametrize('raw', [b'not base64!', b'', b'x' * 65537],
                         ids=['corrupt', 'empty', 'oversized'])
def test_invalid_history_is_bounded_and_does_not_expose_contents(raw):
    with pytest.raises(ValueError):
        decode_guest_history(raw)


@pytest.mark.parametrize('arguments', [[], ['--node', 'node001'],
    ['--local-client-probe', '--node', 'node001'], ['--generate-device']])
def test_probe_cannot_silently_relabel_local_identity_as_a_node(arguments):
    with pytest.raises(ValueError, match='local client identity'):
        require_local_probe(arguments)


def test_explicit_single_client_probe_scope():
    require_local_probe(['--local-client-probe'])
