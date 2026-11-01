import base64
import struct
from urllib.parse import parse_qs

import pytest
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from empire.sources.yuanhang_auth import (
    AuthenticationError,
    ClientDevice,
    GuestSession,
    exchange_frame,
    login_guest,
    login_native,
)
from empire.sources.yuanhang_identity import GuestIdentity


class Response:
    def __init__(self, content):
        self.content, self.closed = content, False

    def close(self):
        self.closed = True
        self.content = b''


class Http:
    def __init__(self, bodies):
        self.responses = [Response(body) for body in bodies]
        self.requests = []

    async def request(self, method, url, **options):
        response = self.responses[len(self.requests)]
        self.requests.append((method, url, options))
        return response


def xml(item):
    return f'<response><ret code="0"/><item {item}/></response>'.encode('gbk')


@pytest.fixture
def authentication():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_numbers()
    bodies = [xml(f'modulus="{public.n:x}" publicExponent="{public.e:x}" rsa_version="1"'),
              xml('userid="fixture-user" sessionid="fixture-session"'),
              xml('passport="UserID=fixture-user|M_hqdns=hevozhuhq1.123ths.com:9602|signlength=4" signature="ABCD"')]
    return key, Http(bodies)


async def test_existing_guest_login_never_registers_or_logs_and_closes_responses(authentication):
    key, http = authentication
    identity = GuestIdentity('thsguest_fixture', 'fixture-secret')
    device = ClientDevice('02-00-00-00-00-01')
    session = await login_guest(http, identity, device, project_id='test-yuanhang', proxy_code='node1')
    assert len(http.requests) == 3 and all(r.closed for r in http.responses)
    assert http.requests[0][1].endswith('?reqtype=do_rsa&type=get_pubkey')
    body = parse_qs(http.requests[1][2]['content'].decode())
    assert body['reqtype'] == ['unified_login']
    for key_name, original in [('account', identity.account), ('passwd', identity.password)]:
        assert key.decrypt(base64.b64decode(body[key_name][0]), padding.PKCS1v15()).decode() == original
    passport_request = parse_qs(http.requests[2][2]['content'].decode(), encoding='gbk')
    assert passport_request['imei'] == [device.imei]
    assert passport_request['sessionid'] == ['fixture-session']
    assert passport_request['reqtype'] == ['verify']
    for method, url, options in http.requests:
        assert options['sensitive'] and options['max_redirects'] == options['max_retries'] == 0
        assert options['project_id'] == 'test-yuanhang'
        assert options['proxy_code'] == 'node1'
        assert 'auto_register' not in url and b'auto_register' not in options.get('content', b'')
    assert session.servers[0].host == 'hevozhuhq1.123ths.com' and session.servers[0].port == 9602
    assert session.proxy_code == 'node1'
    raw = base64.b64decode(session.passport64)
    assert raw[:5] == struct.pack('<hBh', len(raw), 6, 2)
    assert raw[5:7] == b'\x10\x32'  # Source uses low nibble first.
    assert b'signlength' not in raw
    assert raw.endswith(b'\r\n\0')
    assert repr(identity) == 'GuestIdentity()' and repr(device) == 'ClientDevice()'
    assert 'fixture' not in repr(session)


@pytest.mark.parametrize('body', [
    b'<response><ret code="-2">fixture-secret</ret></response>',
    b'<response><ret code="0"/><ret code="0"/><item/></response>',
    b'<!DOCTYPE response [<!ENTITY a "fixture-secret">]><response>&a;</response>',
    b'fixture-secret<broken',
])
async def test_source_rejection_or_invalid_xml_stops_without_registering(body):
    http = Http([body])
    with pytest.raises(AuthenticationError) as caught:
        await login_guest(http, GuestIdentity('thsguest_fixture', 'fixture-secret'),
                          ClientDevice('02-00-00-00-00-01'), project_id='test-yuanhang')
    assert len(http.requests) == 1 and http.responses[0].closed
    assert 'fixture-secret' not in str(caught.value)


async def test_login_rejection_has_no_registration_retry(authentication):
    _, http = authentication
    http.responses[1] = Response(b'<response><ret code="-3">password=fixture-secret</ret></response>')
    with pytest.raises(AuthenticationError) as caught:
        await login_guest(http, GuestIdentity('thsguest_fixture', 'fixture-secret'),
                          ClientDevice('02-00-00-00-00-01'), project_id='test-yuanhang')
    assert caught.value.stage == 'login' and caught.value.code == -3
    assert len(http.requests) == 2 and all(r.closed for r in http.responses[:2])


@pytest.mark.parametrize('bad', [
    'passport="a=b|M_hqdns=outside.example:9602|signlength=4" signature="ABCD"',
    'passport="a=b|M_hqdns=hevozhuhq1.123ths.com:9602" signature="ABCD"',
    'passport="a=b|a=c|signlength=4" signature="ABCD"',
    'passport="a=b|signlength=4" signature="!BAD!"',
])
async def test_passport_format_and_server_allowlist_fail_closed(authentication, bad):
    _, http = authentication
    http.responses[2] = Response(xml(bad))
    with pytest.raises(AuthenticationError, match='passport-format'):
        await login_guest(http, GuestIdentity('thsguest_fixture', 'fixture-secret'),
                          ClientDevice('02-00-00-00-00-01'), project_id='test-yuanhang')
    assert all(r.closed for r in http.responses)


class Channel:
    def __init__(self, reply):
        self.data = b'\xfd' * 4 + f'{len(reply):08x}'.encode() + b'\x09' + reply
        self.sent = []

    async def write(self, data):
        self.sent.append(data)

    async def readexactly(self, size):
        result, self.data = self.data[:size], self.data[size:]
        assert len(result) == size
        return result


async def test_native_login_uses_binary_envelope_and_does_not_decode_binary_as_gbk():
    channel = Channel(b'A\xff\x80\x00VerifyCode=0\r\n')
    session = GuestSession('fixture-user', 'fixture-passport', 'fixture-mac', ())
    await login_native(channel, session)
    payload = channel.sent[0][13:]
    assert payload.startswith(b'A\x09\x00zh_CN.GBK')
    assert b'Passport64=fixture-passport\n' in payload
    assert payload.endswith(b'Mac64=fixture-mac')


@pytest.mark.parametrize('body', [b'VerifyCode=-3\ncredential', b'VerifyCode=0evil', b'VerifyCode=0\nVerifyCode=-3\n'])
async def test_native_rejection_never_echoes_response(body):
    with pytest.raises(AuthenticationError) as caught:
        await login_native(Channel(body), GuestSession('user', 'passport', 'mac', ()))
    assert 'credential' not in str(caught.value)


async def test_unsupported_compression_frame_is_rejected():
    channel = Channel(b'example')
    channel.data = channel.data[:12] + b'\x0a' + channel.data[13:]
    with pytest.raises(ValueError, match='unsupported'):
        await exchange_frame(channel, b'query')


async def test_idle_control_frames_do_not_resend_or_replace_business_response():
    channel = Channel(b'\0' * 4)
    channel.data += Channel(b'valid-business-frame').data
    assert await exchange_frame(channel, b'query', allow_idle=True) == b'valid-business-frame'
    assert len(channel.sent) == 1
    # Similar-looking malformed bodies are never silently discarded.
    assert await exchange_frame(Channel(b'\0' * 3), b'query', allow_idle=True) == b'\0' * 3
    channel = Channel(b'\0' * 4)
    channel.data *= 9
    with pytest.raises(ValueError, match='excessive idle'):
        await exchange_frame(channel, b'query', allow_idle=True)
    assert len(channel.sent) == 1
