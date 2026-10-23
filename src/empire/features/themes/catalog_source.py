"""Anonymous catalog exchange using shared transport; not a registered task.

App revision material is explicitly supplied by the local maintenance boundary.
The first matching subscription response is the app's replacement directory.
"""
import asyncio
import os
import ssl
from dataclasses import dataclass, field
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from empire.features.themes import guest_protocol as wire
from empire.features.themes.catalog_protocol import CatalogError, decode_catalog
from empire.features.themes.guest_crypto import WhiteBoxSM4, sign_gcm
from empire.features.themes.socket_frame import read_frame
from empire.plugins.infra.stream_exchange import StreamTarget


@dataclass(frozen=True)
class GuestMaterial:
    white_box: bytes = field(repr=False)
    message_key: bytes = field(repr=False)
    tls: ssl.SSLContext = field(repr=False)
    version: str = '6.3.20.2'
    channel: int = 1
    api_version: str = 'w48'

    def __post_init__(self):
        if (len(self.white_box) != WhiteBoxSM4.KEY_BYTES or len(self.message_key) != 32
                or self.tls.verify_mode != ssl.CERT_REQUIRED or not self.tls.check_hostname):
            raise ValueError('Verified TLS and valid local guest material required')
        if (self.version, self.channel, self.api_version) != ('6.3.20.2', 1, 'w48'):
            raise ValueError('Guest material revision requires explicit source verification')


class GuestExchange:
    def __init__(self, material):
        self.material = material
        self.aes = AESGCM(material.message_key)

    def _encrypt(self, body, encoding):
        if encoding == 0:
            return body
        nonce = os.urandom(12)
        return nonce + self.aes.encrypt(nonce, body, None)

    def _decode(self, frame, expected_encoding):
        if frame.encoding != expected_encoding:
            raise CatalogError('服务器改变正文加密约定')
        if frame.encoding == 0:
            return frame.body
        if len(frame.body) < 28:
            raise CatalogError('加密正文截断')
        try:
            return self.aes.decrypt(frame.body[:12], frame.body[12:], None)
        except InvalidTag as exc:
            raise CatalogError('加密正文认证失败') from exc

    async def _read(self, channel):
        # A bounded heartbeat window; never wait indefinitely for a matching ID.
        for _ in range(4):
            frame = await read_frame(channel, max_frame_bytes=channel.policy.max_wire_bytes)
            if frame.command in (110, 201):
                # Error command is independent of frame kind/upper format bits.
                # Do not expose source text, which may echo identifiers.
                raise CatalogError('服务器拒绝游客协议请求')
            if frame.kind != 1:
                return frame
        raise CatalogError('等待游客协议响应超过心跳窗口')

    async def __call__(self, channel):
        try:
            return await self.exchange(channel)
        except asyncio.IncompleteReadError as exc:
            # EOF after application framing is not evidence of a failed proxy.
            # Prevent route failover from replaying an entire rejected handshake.
            raise CatalogError('游客连接在完整响应前结束') from exc

    async def exchange(self, channel):
        material = self.material
        await channel.writer.start_tls(material.tls, server_hostname='socket.kaipan.com',
                                       ssl_handshake_timeout=8)
        greeting = await self._read(channel)
        if (greeting.kind, greeting.command, greeting.format_code, greeting.encoding) != (2, 260, 0, 0):
            raise CatalogError('未收到已核实游客挑战消息')
        challenge = wire.challenge(greeting.body)
        device = uuid4().hex
        plain = (f'kp26{device}1{material.version}{material.channel}99'
                 f'{challenge.server_time}{material.api_version}').encode()
        signature = challenge.nonce + sign_gcm(WhiteBoxSM4(material.white_box).encrypt,
                                                challenge.nonce, plain)
        body = wire.auth_body(device, signature, version=material.version,
                              channel=material.channel, api_version=material.api_version)
        await channel.write(wire.request(610, self._encrypt(body, challenge.encoding),
                            sequence=1, kind=3, format_code=2, encoding=challenge.encoding))
        response = await self._read(channel)
        if (response.kind, response.command, response.sequence, response.format_code) != (3, 610, 1, 2):
            raise CatalogError('游客认证回复不匹配')
        auth = wire.fields(self._decode(response, challenge.encoding), {1: 2})
        try:
            server = auth[1].decode('utf8')
            if not server or len(server) > 128 or '\0' in server:
                raise ValueError('Invalid server identifier')
        except (KeyError, ValueError, UnicodeError) as exc:
            raise CatalogError('游客认证回复字段无效') from exc
        await channel.write(wire.request(3009, self._encrypt(b'', challenge.encoding),
                            sequence=2, kind=4, format_code=0, encoding=challenge.encoding,
                            subscription=3009))
        response = await self._read(channel)
        if (response.kind, response.command, response.sequence, response.format_code) != (4, 3009, 2, 0):
            raise CatalogError('题材首次订阅回复不匹配')
        if dict(response.extensions).get(2) != 3009:
            raise CatalogError('题材订阅身份不匹配')
        body = self._decode(response, challenge.encoding)
        catalog = decode_catalog(body)
        if catalog.state != 0 or catalog.code_switch != 0:
            raise CatalogError('题材目录状态改变，须重新核实来源契约')
        return body


async def fetch_catalog(http, material):
    target = StreamTarget('hwsockapp.longhuvip.com', 17000,
                          'https://hwsockapp.longhuvip.com/', ('longhuvip.com',))
    response = await http.request_stream(target, GuestExchange(material),
                                        policy=http.response_policy('generic'),
                                        max_retries=0, total_timeout=30)
    try:
        return decode_catalog(response.content)
    finally:
        response.close()
