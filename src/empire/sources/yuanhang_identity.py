"""Read one installed Yuanhang guest identity for authorized protocol research.

No registration, identity generation, client writes or credential export. The
current NEW history format is explicit; legacy files are not silently searched.
"""
import base64
import binascii
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from xml.etree import ElementTree

_ALPHABET = b'oPbsG4EvU8gyd02B3q6fIVWXYZaCcMeTKhxnwzmjApRrDtuHkiLlN1O9F5S7JQ+/'
_BASE64 = b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
MAX_HISTORY_BYTES = 65536


def require_local_probe(arguments: list[str]) -> None:
    """Local device identity is opt-in; this is not a proxy-node identity API."""
    if arguments != ['--local-client-probe']:
        raise ValueError('This probe uses the installed local client identity; '
                         'explicit --local-client-probe is required. '
                         'Proxy-node or generated-device identities are unsupported.')


@dataclass(frozen=True)
class GuestIdentity:
    account: str = field(repr=False)
    password: str = field(repr=False)


def history_filename(client_bin: str) -> str:
    """Client's CRC16/MODBUS installation identity, GBK and little-endian hex."""
    directory = PureWindowsPath(client_bin)
    if not directory.is_absolute():
        raise ValueError('Guest client installation path must be absolute')
    crc = 0xffff
    for byte in str(directory).encode('gbk'):
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xa001 if crc & 1 else crc >> 1
    return crc.to_bytes(2, 'little').hex().upper() + '_NEW.dat'


def decode_guest_history(raw: bytes) -> GuestIdentity:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_HISTORY_BYTES:
        raise ValueError('Guest history size invalid')
    try:
        xml = base64.b64decode(raw.translate(bytes.maketrans(_ALPHABET, _BASE64)), validate=True)
        if b'<!DOCTYPE' in xml or b'<!ENTITY' in xml:
            raise ValueError
        root = ElementTree.fromstring(xml)
        if root.tag != 'UserRecordHistory':
            raise ValueError
        active = root.get('ActiveUser', '')
        guests = [record for record in root if record.tag == 'UserRecord'
                  and record.get('InputedUserName', '').startswith('thsguest_')]
        # Never select a different account when the client has an active identity.
        if active:
            guests = [record for record in guests if record.get('InputedUserName') == active]
        if len(guests) != 1:
            raise ValueError
        record = guests[0]
        account = record.get('InputedUserName', '')
        # NEW history wraps the login secret in standard Base64 inside the outer
        # Hexin-Base64 XML. Sending SavedPassword directly causes login code -3.
        password = base64.b64decode(record.get('SavedPassword', ''), validate=True).decode('ascii')
        if (not 10 <= len(account) <= 128 or not 1 <= len(password) <= 512
                or not account.isascii() or any(ord(c) < 33 for c in account + password)):
            raise ValueError
        return GuestIdentity(account, password)
    except (ValueError, binascii.Error, UnicodeError, ElementTree.ParseError):
        raise ValueError('Saved guest identity unavailable or unsupported') from None


def read_guest(client_bin: str, roaming_appdata: Path) -> GuestIdentity:
    """Read only the exact installation's NEW history, with bounded allocation."""
    path = roaming_appdata / 'HeUsr' / history_filename(client_bin)
    try:
        with path.open('rb') as handle:
            raw = handle.read(MAX_HISTORY_BYTES + 1)
    except OSError:
        raise ValueError('Installed client guest history is unavailable') from None
    return decode_guest_history(raw)
