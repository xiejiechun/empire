"""Immutable, allowlisted guest creation recipes; transient login tokens excluded."""
import hashlib
from datetime import UTC, datetime

from empire.sources.yuanhang_auth import VERSION, ClientDevice

ENDPOINT = 'http://auth.10jqka.com.cn/verify'


def timestamp():
    return datetime.now(UTC).isoformat()


def logical_device(profile_id):
    octets = bytes([2]) + hashlib.sha256(profile_id.encode()).digest()[:5]
    return ClientDevice('-'.join(f'{v:02X}' for v in octets))


def creation_recipe(profile_id, *, legacy=False):
    device = logical_device(profile_id)
    return dict(recipe_version=1, provenance='legacy-reconstructed' if legacy else 'recorded',
                recorded_at=timestamp(), requested_at=None,
                client_version='12.1.1.6' if legacy else VERSION,
                device_mac=device.mac, imei=device.imei, endpoint=ENDPOINT, method='GET',
                params=dict(imei=device.imei, qsid='800', reqtype='auto_register'))


def validate_recipe(value, profile_id):
    keys = {'recipe_version', 'provenance', 'recorded_at', 'requested_at', 'client_version',
            'device_mac', 'imei', 'endpoint', 'method', 'params'}
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError('Invalid guest creation recipe')
    device = logical_device(profile_id)
    if (type(value['recipe_version']) is not int or value['recipe_version'] != 1
            or value['provenance'] not in {'recorded', 'legacy-reconstructed'}
            or value['device_mac'] != device.mac or value['imei'] != device.imei
            or value['endpoint'] != ENDPOINT or value['method'] != 'GET'
            or value['params'] != dict(imei=device.imei, qsid='800', reqtype='auto_register')
            or not isinstance(value['client_version'], str) or not 1 <= len(value['client_version']) <= 64):
        raise ValueError('Unsupported guest creation recipe; preserve the existing identity')
    for key in ('recorded_at', 'requested_at'):
        raw = value[key]
        if raw is None and key == 'requested_at':
            continue
        if not isinstance(raw, str) or len(raw) > 40 or datetime.fromisoformat(raw).tzinfo is None:
            raise ValueError('Invalid recipe timestamp')
    return device
