import base64
import os
import tomllib
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from empire.features.themes.guest_crypto import WhiteBoxSM4
from empire.features.themes.guest_material import (
    build_material,
    import_material,
    load_material,
    protect_material,
)


@pytest.fixture(scope='module')
def local_material():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Synthetic test CA')])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(1)
            .not_valid_before(datetime.now(UTC) - timedelta(days=1))
            .not_valid_after(datetime.now(UTC) + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    values = {'white_box': bytes(WhiteBoxSM4.KEY_BYTES), 'message_key': bytes(32),
              'ca': cert.public_bytes(serialization.Encoding.PEM),
              'client_p12': pkcs12.serialize_key_and_certificates(
                  b'test', key, cert, None, serialization.BestAvailableEncryption(b'synthetic')),
              'client_password': b'synthetic'}
    return {'schema': 1, **{k: base64.b64encode(v).decode() for k, v in values.items()}}


def test_material_build_never_exposes_values_in_repr(local_material):
    material = build_material(local_material)
    assert material.tls.check_hostname
    assert 'white_box' not in repr(material)
    assert 'message_key' not in repr(material)


@pytest.mark.skipif(os.name != 'nt', reason='Windows DPAPI contract')
def test_protected_config_round_trip_preserves_existing_bytes(tmp_path, local_material):
    config = tmp_path / 'config.toml'
    original = b'# original\r\n[mysql]\r\nuser="synthetic"\r\n'
    config.write_bytes(original)
    import_material(config, local_material)
    output = config.read_bytes()
    assert output.startswith(original)
    settings = tomllib.loads(output.decode())['kaipanla_guest']
    assert load_material(settings).message_key == bytes(32)
    with pytest.raises(ValueError, match='已有'):
        import_material(config, local_material)
    assert config.read_bytes() == output
    assert not list(tmp_path.glob('.theme-config-*.tmp'))


@pytest.mark.skipif(os.name != 'nt', reason='Windows DPAPI contract')
def test_corrupt_protected_material_fails_without_exposing_data(local_material):
    token = protect_material(local_material)
    raw = bytearray(base64.b64decode(token))
    raw[-10] ^= 1
    with pytest.raises(ValueError, match='不可用'):
        load_material({'protected_material_secret': base64.b64encode(raw).decode()})


def test_existing_quoted_or_inline_section_cannot_be_overwritten(tmp_path, local_material):
    for original in (b'["kaipanla_guest"] # comment\nx=1\n', b'kaipanla_guest={x=1}\n'):
        path = tmp_path / 'config.toml'
        path.write_bytes(original)
        with pytest.raises(ValueError, match='已有'):
            import_material(path, local_material)
        assert path.read_bytes() == original


def test_protected_config_field_uses_shared_redaction():
    from empire.core.redaction import REDACTED, Redactor
    value = {'protected_material_secret': 'synthetic-sensitive-data'}
    assert Redactor().value(value) == {'protected_material_secret': REDACTED}


def test_invalid_bundle_does_not_change_config(tmp_path, local_material):
    path = tmp_path / 'config.toml'
    path.write_bytes(b'# unchanged\n')
    with pytest.raises(ValueError):
        import_material(path, local_material | {'schema': 2})
    assert path.read_bytes() == b'# unchanged\n'
