import random

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from empire.features.themes.guest_crypto import WhiteBoxSM4, sign_gcm


@pytest.mark.parametrize(('block', 'expected'), [
    (bytes(16), '76a33fdc638867ff365fe3d02bbb2e71'),
    (bytes(range(16)), '753c8f395bae86a412732036de442b60'),
    (bytes([255]) * 16, '95d135862e199e0222724905dadefee9'),
])
def test_portable_layout_against_native_with_synthetic_material(block, expected):
    # Generated test material, not any application's secret tables. Expected
    # vectors obtained from offline execution of the inspected block primitive.
    material = random.Random(20261024).randbytes(WhiteBoxSM4.KEY_BYTES)
    assert WhiteBoxSM4(material).encrypt(block).hex() == expected


@pytest.mark.parametrize('size', [0, 1, 15, 16, 17, 100, 1024])
def test_gcm_against_independent_library(size):
    key, nonce = bytes(range(16)), bytes(range(12))
    plaintext = bytes(i % 256 for i in range(size))
    encrypt = Cipher(algorithms.AES(key), modes.ECB()).encryptor().update
    assert sign_gcm(encrypt, nonce, plaintext) == AESGCM(key).encrypt(nonce, plaintext, None)


def test_limits_and_no_secret_repr():
    with pytest.raises(ValueError):
        WhiteBoxSM4(b'wrong')
    cipher = WhiteBoxSM4(bytes(WhiteBoxSM4.KEY_BYTES))
    with pytest.raises(ValueError):
        cipher.encrypt(b'wrong')
    with pytest.raises(ValueError):
        sign_gcm(cipher.encrypt, bytes(11), b'')
    with pytest.raises(ValueError):
        sign_gcm(cipher.encrypt, bytes(12), bytes(1025))

