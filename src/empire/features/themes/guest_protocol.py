"""Strict small protobuf messages used by the verified guest handshake."""
import re
from dataclasses import dataclass

from empire.features.themes.catalog_protocol import CatalogError, _varint


def varint(value):
    output = bytearray()
    while value > 127:
        output.append((value & 127) | 128)
        value >>= 7
    output.append(value)
    return bytes(output)


def field(key, value):
    if isinstance(value, int):
        return varint(key * 8) + varint(value)
    body = value.encode('utf8') if isinstance(value, str) else value
    return varint(key * 8 + 2) + varint(len(body)) + body


def fields(body, schema):
    if len(body) > 4096:
        raise CatalogError('游客协议正文超限')
    result, offset = {}, 0
    while offset < len(body):
        tag, offset = _varint(body, offset)
        key, wire = tag >> 3, tag & 7
        if key in result or schema.get(key) != wire:
            raise CatalogError('游客协议字段重复或结构改变')
        if wire == 0:
            value, offset = _varint(body, offset)
        else:
            size, offset = _varint(body, offset)
            value = body[offset:offset + size]
            if len(value) != size:
                raise CatalogError('游客协议字段截断')
            offset += size
        result[key] = value
    return result


@dataclass(frozen=True)
class Challenge:
    server_time: int
    nonce: bytes
    encoding: int


def challenge(body):
    data = fields(body, {1: 0, 2: 2, 3: 0})
    timestamp, nonce, encoding = data.get(1), data.get(2), data.get(3, 0)
    if (not isinstance(timestamp, int) or timestamp <= 0
            or not isinstance(nonce, bytes) or not re.fullmatch(rb'[A-Za-z0-9]{12,128}', nonce)
            or encoding not in (0, 1)):
        raise CatalogError('游客挑战参数不符合已核实契约')
    return Challenge(timestamp, nonce[:12], encoding)


def auth_body(device, signature, *, version, channel, api_version):
    if not re.fullmatch('[a-f0-9]{32}', device):
        raise ValueError('Device must be a fresh anonymous UUID hex string')
    return b''.join(field(key, value) for key, value in (
        (1, device), (2, 1), (3, version), (4, channel), (5, signature.hex()),
        (6, '0'), (8, 99), (10, api_version)))


def request(command, body, *, sequence, kind, format_code, encoding, subscription=None):
    if (kind not in (3, 4) or not 1 <= sequence <= 32766
            or not 1 <= command <= 65535 or format_code not in (0, 2)
            or encoding not in (0, 1) or len(body) > 4096):
        raise ValueError('Unsupported guest request')
    extensions = b'' if subscription is None else b'\x02' + subscription.to_bytes(2, 'big')
    payload = (sequence.to_bytes(2, 'big') + command.to_bytes(2, 'big')
               + bytes([format_code * 8 + encoding])
               + len(extensions).to_bytes(2, 'big') + extensions + body)
    return bytes([kind << 4]) + len(payload).to_bytes(4, 'big') + payload
