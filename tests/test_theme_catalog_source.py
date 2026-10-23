import asyncio
import ssl
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from empire.features.themes import guest_protocol as wire
from empire.features.themes.catalog_protocol import CatalogError
from empire.features.themes.catalog_source import GuestExchange, GuestMaterial, fetch_catalog
from empire.features.themes.guest_crypto import WhiteBoxSM4
from empire.features.themes.socket_frame import read_frame


def material():
    return GuestMaterial(bytes(WhiteBoxSM4.KEY_BYTES), bytes(32), ssl.create_default_context())


def encode(body):
    nonce = bytes(12)
    return nonce + AESGCM(bytes(32)).encrypt(nonce, body, None)


def reply(command, body, sequence=1, kind=3, format_code=2, subscription=None):
    return wire.request(command, encode(body), sequence=sequence, kind=kind,
                        format_code=format_code, encoding=1, subscription=subscription)


def greeting():
    body = wire.field(1, 1792800000000) + wire.field(2, 'a' * 32) + wire.field(3, 1)
    payload = b'\x01\x04\x00\x00\x00' + body
    return b'\x20' + len(payload).to_bytes(4, 'big') + payload


def catalog():
    return wire.field(10, wire.field(1, '148') + wire.field(2, '军工'))


class Channel:
    def __init__(self, response):
        self.reader = asyncio.StreamReader()
        self.reader.feed_data(response)
        self.reader.feed_eof()
        self.writer = self
        self.sent = []
        self.policy = SimpleNamespace(max_wire_bytes=1048576)

    async def start_tls(self, context, **options):
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname
        assert options['server_hostname'] == 'socket.kaipan.com'

    async def readexactly(self, size):
        return await self.reader.readexactly(size)

    async def write(self, body):
        self.sent.append(body)


def responses():
    return (greeting() + reply(610, wire.field(1, '127.0.0.1'))
            + reply(3009, catalog(), 2, 4, 0, 3009))


async def sent_auth(channel):
    reader = asyncio.StreamReader()
    reader.feed_data(channel.sent[0])
    frame = await read_frame(reader, max_frame_bytes=4096)
    body = AESGCM(bytes(32)).decrypt(frame.body[:12], frame.body[12:], None)
    return wire.fields(body, {1: 2, 2: 0, 3: 2, 4: 0, 5: 2, 6: 2, 7: 2, 8: 0, 10: 2})


async def test_anonymous_session_and_complete_subscription():
    first, second = Channel(responses()), Channel(responses())
    exchange = GuestExchange(material())
    assert await exchange(first) == catalog()
    assert await exchange(second) == catalog()
    auth1, auth2 = await sent_auth(first), await sent_auth(second)
    assert auth1[6] == b'0' and 7 not in auth1
    assert auth1[1] != auth2[1]  # Every attempt has a new guest identity.
    assert len(first.sent) == 2


@pytest.mark.parametrize('command', [110, 201])
async def test_error_commands_stop_before_catalog_request(command):
    channel = Channel(greeting() + reply(command, wire.field(1, 1)))
    with pytest.raises(CatalogError, match='拒绝'):
        await GuestExchange(material())(channel)
    assert len(channel.sent) == 1


async def test_truncated_session_is_business_error_not_route_retry():
    channel = Channel(responses()[:-1])
    with pytest.raises(CatalogError, match='完整响应'):
        await GuestExchange(material())(channel)


async def test_modified_ciphertext_rejected():
    data = bytearray(responses())
    data[-1] ^= 1
    with pytest.raises(CatalogError, match='认证失败'):
        await GuestExchange(material())(Channel(bytes(data)))


@pytest.mark.parametrize(('sequence', 'subscription'), [(3, 3009), (2, 3008)])
async def test_wrong_response_identity(sequence, subscription):
    channel = Channel(greeting() + reply(610, wire.field(1, '127.0.0.1'))
                      + reply(3009, catalog(), sequence, 4, 0, subscription))
    with pytest.raises(CatalogError, match='不匹配'):
        await GuestExchange(material())(channel)


async def test_unknown_directory_state_rejected():
    channel = Channel(greeting() + reply(610, wire.field(1, '127.0.0.1'))
                      + reply(3009, wire.field(2, 1) + catalog(), 2, 4, 0, 3009))
    with pytest.raises(CatalogError, match='状态改变'):
        await GuestExchange(material())(channel)


async def test_response_lease_released_after_parse_failure():
    response = SimpleNamespace(content=b'invalid', close=lambda: closed.append(True))
    closed = []

    async def request_stream(*args, **kwargs):
        assert kwargs['max_retries'] == 0
        return response

    http = SimpleNamespace(request_stream=request_stream, response_policy=lambda _: None)
    with pytest.raises(CatalogError):
        await fetch_catalog(http, material())
    assert closed == [True]


def test_no_tls_verification_bypass():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    with pytest.raises(ValueError):
        GuestMaterial(bytes(WhiteBoxSM4.KEY_BYTES), bytes(32), context)


@pytest.mark.parametrize('data', [wire.field(1, 1) * 2, b'\x12\x80', wire.field(4, 1)])
def test_challenge_invalid_structure(data):
    with pytest.raises(CatalogError):
        wire.challenge(data)
