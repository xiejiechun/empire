"""Normal existing-guest authentication on the shared downloader.

Callers supply an explicit client protocol identifier and an existing identity.
Logical node profiles are managed separately; identifiers are never inferred from an IP.
Sessions live only in memory and contain no guessed persistence/expiry contract.
"""
import base64
import hashlib
import re
import struct
from dataclasses import dataclass, field
from urllib.parse import urlencode
from xml.etree import ElementTree

from cryptography.hazmat.primitives.asymmetric import padding, rsa

from empire.contracts.download import ResponsePolicy
from empire.contracts.native_stream import StreamTarget
from empire.sources.yuanhang_identity import GuestIdentity

AUTH_URL = 'http://auth.10jqka.com.cn/verify2'
VERSION = '12.1.1.6'
AUTH_POLICY = ResponsePolicy(131072, 131072)


class AuthenticationError(ValueError):
    def __init__(self, stage: str, code: int | None = None):
        super().__init__(f'Yuanhang authentication failed at {stage}'
                         + (f' (code={code})' if code is not None else ''))
        self.stage, self.code = stage, code


@dataclass(frozen=True)
class ClientDevice:
    mac: str = field(repr=False)

    def __post_init__(self):
        if not isinstance(self.mac, str) or not re.fullmatch(r'(?:[0-9A-F]{2}-){5}[0-9A-F]{2}', self.mac):
            raise ValueError('Yuanhang client MAC text must be explicitly supplied in client format')

    @property
    def imei(self):
        return hashlib.md5((self.mac + '0' * 30).encode('ascii')).hexdigest()

    @property
    def mac64(self):
        return base64.b64encode(self.mac.encode('ascii')).decode('ascii')


@dataclass(frozen=True)
class GuestSession:
    user_id: str = field(repr=False)
    passport64: str = field(repr=False)
    mac64: str = field(repr=False)
    servers: tuple[StreamTarget, ...]
    proxy_code: str | None = None


def _token(value, maximum=4096):
    if (not isinstance(value, str) or not 1 <= len(value) <= maximum
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('Invalid authentication token')
    return value


def _item(body: bytes, stage: str):
    try:
        if not body or len(body) > AUTH_POLICY.max_body_bytes:
            raise ValueError
        if b'<!DOCTYPE' in body or b'<!ENTITY' in body:
            raise ValueError
        root = ElementTree.fromstring(body.decode('gbk'))
        results, items = root.findall('ret'), root.findall('item')
        if len(results) != 1:
            raise ValueError
        code = int(results[0].get('code', ''))
        if code != 0:
            raise AuthenticationError(stage, code)
        if len(items) != 1:
            raise ValueError
        return items[0]
    except AuthenticationError:
        raise
    except (ValueError, UnicodeError, ElementTree.ParseError):
        raise AuthenticationError(stage) from None


async def _request_item(http, project_id, stage, params=None, *, proxy_code=None):
    options = dict(allowed_domains=('10jqka.com.cn',), policy=AUTH_POLICY,
                   max_retries=0, max_redirects=0, total_timeout=30,
                   project_id=project_id, sensitive=True, proxy_code=proxy_code)
    if params is None:
        response = await http.request('GET', AUTH_URL + '?reqtype=do_rsa&type=get_pubkey', **options)
    else:
        response = await http.request('POST', AUTH_URL,
            content=urlencode(params, encoding='gbk').encode('ascii'),
            headers={'Content-Type': 'application/x-www-form-urlencoded'}, **options)
    try:
        return _item(response.content, stage)
    finally:
        response.close()


def _passport(item, user_id, device, proxy_code=None):
    try:
        text = _token(item.get('passport'), 65536)
        signature = _token(item.get('signature'), 8192)
        if len(signature) % 2 or not re.fullmatch('[A-P]+', signature):
            raise ValueError
        parts = [part.split('=', 1) for part in text.split('|') if part]
        if any(len(part) != 2 for part in parts) or len({part[0] for part in parts}) != len(parts):
            raise ValueError
        attributes = dict(parts)
        if '|signlength=' not in text:
            raise ValueError
        signature_bytes = bytes((ord(signature[i]) - 65) + (ord(signature[i + 1]) - 65) * 16
                                for i in range(0, len(signature), 2))
        plain = (text[:text.index('|signlength=')].replace('|', '\r\n') + '\r\n').encode('gbk')
        size = 5 + len(signature_bytes) + len(plain) + 1
        if size > 32767:
            raise ValueError
        passport64 = base64.b64encode(struct.pack('<hBh', size, 6, len(signature_bytes))
                                     + signature_bytes + plain + b'\0').decode('ascii')
        directory = attributes.get('M_hqdns', '').split(',')
        if not 1 <= len(directory) <= 64:
            raise ValueError
        servers = []
        for address in directory:
            fields = address.split(':')
            if len(fields) < 2:
                raise ValueError
            servers.append(StreamTarget(fields[0], int(fields[1]), 'https://10jqka.com.cn/',
                                         ('10jqka.com.cn', '123ths.com')))
        return GuestSession(user_id, passport64, device.mac64, tuple(dict.fromkeys(servers)), proxy_code)
    except (ValueError, UnicodeError, struct.error):
        raise AuthenticationError('passport-format') from None


async def login_guest(http, identity: GuestIdentity, device: ClientDevice, *, project_id: str,
                      proxy_code: str | None = None) -> GuestSession:
    """Reuse one normal guest. A source rejection never triggers auto_register."""
    if not isinstance(identity, GuestIdentity) or not isinstance(device, ClientDevice) or not project_id:
        raise ValueError('Yuanhang login requires explicit identity, device and project')
    try:
        if not _token(identity.account, 128).startswith('thsguest_'):
            raise ValueError
        _token(identity.password, 512)
    except ValueError:
        raise AuthenticationError('identity') from None
    public = await _request_item(http, project_id, 'public-key', proxy_code=proxy_code)
    try:
        modulus = public.get('modulus', '')
        exponent = public.get('publicExponent', '')
        if not re.fullmatch('[0-9a-fA-F]{256,1024}', modulus) or not re.fullmatch('[0-9a-fA-F]{1,8}', exponent):
            raise ValueError
        key = rsa.RSAPublicNumbers(int(exponent, 16), int(modulus, 16)).public_key()
        version = _token(public.get('rsa_version'), 128)
        credentials = {name: base64.b64encode(key.encrypt(value.encode('gbk'), padding.PKCS1v15())).decode('ascii')
                       for name, value in (('account', identity.account), ('passwd', identity.password))}
    except (ValueError, UnicodeError):
        raise AuthenticationError('public-key-format') from None
    session = await _request_item(http, project_id, 'login', dict(
        reqtype='unified_login', **credentials, rsa_version=version, ta_appid='2022021120720687'), proxy_code=proxy_code)
    try:
        user_id, session_id = _token(session.get('userid'), 128), _token(session.get('sessionid'))
    except ValueError:
        raise AuthenticationError('session-format') from None
    passport = await _request_item(http, project_id, 'passport', dict(
        reqtype='verify', product='S01', imei=device.imei, userid=user_id, sessionid=session_id,
        qsid='800', version=VERSION, sdsn='', securities='同花顺远航版', nohqlist='0', newwgflag='3'), proxy_code=proxy_code)
    return _passport(passport, user_id, device, proxy_code)


async def exchange_frame(channel, payload: bytes, *, allow_idle=False) -> bytes:
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= 65523:
        raise ValueError('Yuanhang outbound frame exceeds bounds')
    await channel.write(b'\xfd' * 4 + f'{len(payload):08x}'.encode('ascii') + b'\x09' + payload)
    # An idle native connection can contain four-zero control frames. Consume
    # only this exact frame, without resending the query or accepting it as data.
    # Both frame count and the shared channel's byte/time budget remain bounded.
    for _ in range(9):
        header = await channel.readexactly(13)
        if (header[:4] != b'\xfd' * 4 or header[-1] != 9
                or not re.fullmatch(b'[0-9a-fA-F]{8}', header[4:12])):
            raise ValueError('Yuanhang unsupported or malformed frame')
        body = await channel.readexactly(int(header[4:12], 16))
        if not allow_idle or body != b'\0' * 4:
            return body
    raise ValueError('Yuanhang excessive idle control frames')


async def login_native(channel, session: GuestSession):
    entries = {'Ask': 'login', 'C-Version': 'hevo_' + VERSION, 'UserName': session.user_id,
               'C-Language': 'zh_CN.GBK', 'Qsid': '800', 'Passport64': session.passport64,
               'VerifyType': '1', 'Mac64': session.mac64}
    fields = '\n'.join(k + '=' + _token(v, 65536) for k, v in entries.items()).encode('gbk')
    charset = b'zh_CN.GBK'
    if len(fields) > 65000:
        raise AuthenticationError('native-login-size')
    reply = await exchange_frame(channel, b'A' + struct.pack('<H', len(charset)) + charset
                                  + struct.pack('<H', len(fields)) + fields)
    codes = re.findall(rb'VerifyCode=(-?[0-9]+)(?=[\r\n\x00]|$)', reply)
    if len(codes) != 1 or codes[0] != b'0':
        raise AuthenticationError('native-login', int(codes[0]) if len(codes) == 1 else None)
