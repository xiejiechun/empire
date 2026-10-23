"""Guest protocol primitives. Application key material is supplied locally.

No account, token, APK, private certificate or source key is bundled here.
The white-box layout is specific to the inspected app revision, not general SM4.
"""
import struct


class WhiteBoxSM4:
    KEY_BYTES = 284320

    def __init__(self, material: bytes):
        if not isinstance(material, bytes) or len(material) != self.KEY_BYTES:
            raise ValueError("Unsupported white-box material layout")
        self._material = material

    def _affine(self, offset, value):
        rows = struct.unpack_from('<33I', self._material, offset)
        return sum(((row & value).bit_count() % 2) << (31 - i)
                   for i, row in enumerate(rows[:32])) ^ rows[32]

    def encrypt(self, block: bytes) -> bytes:
        if not isinstance(block, bytes) or len(block) != 16:
            raise ValueError("Expected one 16-byte block")
        words = [self._affine(0x5280 + i * 132, value)
                 for i, value in enumerate(struct.unpack('>4I', block))]
        for round_no in range(32):
            value = (self._affine(round_no * 396, words[1])
                     ^ self._affine(round_no * 396 + 132, words[2])
                     ^ self._affine(round_no * 396 + 264, words[3]))
            table_value = 0
            for lane, shift in enumerate((24, 16, 8, 0)):
                offset = (0x56a0 + round_no * 8192 + lane * 2048
                          + ((value >> shift) & 255) * 8)
                table_value ^= struct.unpack_from('<Q', self._material, offset)[0]
            value = (self._affine(0x3180 + round_no * 132, words[0])
                     ^ self._affine(0x4200 + round_no * 132, table_value >> 32))
            words = words[1:] + [value]
        return struct.pack('>4I', *[self._affine(0x5490 + i * 132, value)
                                   for i, value in enumerate(reversed(words))])


def _multiply(left, right):
    result = 0
    for index in range(128):
        if left & (1 << (127 - index)):
            result ^= right
        right = (right >> 1) ^ ((0xe1 << 120) if right & 1 else 0)
    return result


def sign_gcm(encrypt_block, nonce: bytes, plaintext: bytes) -> bytes:
    """Small bounded guest signature, ciphertext followed by the 16-byte tag.

    No generic message encryption or decryption API is provided by this helper.
    TLS and subsequent AES-GCM messages use platform/cryptography primitives.
    """
    if not isinstance(nonce, bytes) or len(nonce) != 12:
        raise ValueError("Guest signature requires a 12-byte nonce")
    if not isinstance(plaintext, bytes) or len(plaintext) > 1024:
        raise ValueError("Guest signature plaintext exceeds contract")
    hash_key = int.from_bytes(encrypt_block(bytes(16)), 'big')
    ciphertext = bytearray()
    for offset in range(0, len(plaintext), 16):
        counter = nonce + (2 + offset // 16).to_bytes(4, 'big')
        ciphertext.extend(a ^ b for a, b in
                          zip(plaintext[offset:offset + 16], encrypt_block(counter)))
    authenticated = (bytes(ciphertext) + bytes((-len(ciphertext)) % 16)
                     + bytes(8) + (len(ciphertext) * 8).to_bytes(8, 'big'))
    digest = 0
    for offset in range(0, len(authenticated), 16):
        digest = _multiply(digest ^ int.from_bytes(authenticated[offset:offset + 16], 'big'),
                           hash_key)
    tag = bytes(a ^ b for a, b in zip(digest.to_bytes(16, 'big'),
                                    encrypt_block(nonce + b'\0\0\0\1')))
    return bytes(ciphertext) + tag
