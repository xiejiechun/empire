"""Local guest material protected by the current Windows user's DPAPI.

Stored in the existing program config so release preserves it with that file.
No account credentials or application binary is read by the collector.
"""
import base64
import ctypes
import json
import os
import ssl
import tempfile
import tomllib
from ctypes import wintypes
from pathlib import Path

from cryptography.hazmat.primitives.serialization import (
    BestAvailableEncryption,
    Encoding,
    PrivateFormat,
    pkcs12,
)

from empire.features.themes.catalog_source import GuestMaterial

FIELDS = {'schema', 'white_box', 'message_key', 'ca', 'client_p12', 'client_password'}


class _Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data, *, decrypt):
    if os.name != 'nt':
        raise RuntimeError('游客协议材料当前仅支持Windows用户保护')
    buffer = ctypes.create_string_buffer(data)
    incoming = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = _Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    method = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    method.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                       ctypes.POINTER(_Blob)]
    method.restype = wintypes.BOOL
    if not method(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise ValueError('游客协议材料无法由当前Windows用户读取或保护')
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        kernel.LocalFree(outgoing.data)


def _decode(data):
    if (not isinstance(data, dict) or set(data) != FIELDS
            or type(data['schema']) is not int or data['schema'] != 1):
        raise ValueError('游客协议材料结构无效')
    result = {}
    for name in FIELDS - {'schema'}:
        if not isinstance(data[name], str) or len(data[name]) > 400000:
            raise ValueError('游客协议材料字段超限')
        try:
            result[name] = base64.b64decode(data[name], validate=True)
        except ValueError as exc:
            raise ValueError('游客协议材料编码无效') from exc
    return result


def build_material(data):
    values = _decode(data)
    try:
        key, certificate, chain = pkcs12.load_key_and_certificates(
            values['client_p12'], values['client_password'])
        if key is None or certificate is None:
            raise ValueError('Missing client certificate')
        context = ssl.create_default_context(cadata=values['ca'].decode('ascii'))
        password = os.urandom(32)
        # ssl requires a filename. The short-lived private key remains encrypted
        # with an in-memory random password, including on abnormal process exit.
        with tempfile.TemporaryDirectory(prefix='empire-theme-tls-') as directory:
            path = Path(directory) / 'client.pem'
            path.write_bytes(certificate.public_bytes(Encoding.PEM)
                             + b''.join(c.public_bytes(Encoding.PEM) for c in (chain or []))
                             + key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8,
                                                 BestAvailableEncryption(password)))
            context.load_cert_chain(str(path), password=password)
        return GuestMaterial(values['white_box'], values['message_key'], context)
    except Exception as exc:
        raise ValueError('游客协议材料校验失败，须重新执行显式导入') from exc


def protect_material(data):
    build_material(data)
    raw = json.dumps(data, sort_keys=True, separators=(',', ':')).encode()
    if len(raw) > 500000:
        raise ValueError('游客协议材料总长度超限')
    return base64.b64encode(_dpapi(raw, decrypt=False)).decode('ascii')


def load_material(settings):
    if not isinstance(settings, dict) or set(settings) != {'protected_material_secret'}:
        raise ValueError('缺少游客协议材料，请先执行显式维护导入')
    token = settings['protected_material_secret']
    if not isinstance(token, str) or not 1 <= len(token) <= 700000:
        raise ValueError('游客协议材料长度无效')
    try:
        raw = _dpapi(base64.b64decode(token, validate=True), decrypt=True)
        if len(raw) > 500000:
            raise ValueError('Invalid material size')
        return build_material(json.loads(raw))
    except Exception as exc:
        raise ValueError('游客协议材料不可用，请使用当前Windows用户显式重新导入') from exc


def import_material(config_path, data):
    """Explicit one-time append; never overwrite an existing material section."""
    path = Path(config_path).resolve()
    original = path.read_bytes()
    parsed = tomllib.loads(original.decode('utf-8-sig'))
    if 'kaipanla_guest' in parsed:
        raise ValueError('配置中已有游客协议材料，拒绝覆盖')
    protected = protect_material(data)
    addition = f'\n[kaipanla_guest]\nprotected_material_secret = "{protected}"\n'.encode()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.theme-config-',
                                         suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
            output.write(original + addition)
            output.flush()
            os.fsync(output.fileno())
        if path.read_bytes() != original:
            raise ValueError('导入期间配置发生变化')
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
