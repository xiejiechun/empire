"""Windows current-user DPAPI for local source credentials; no plaintext fallback."""
import ctypes
import os
from ctypes import wintypes


class _Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


class WindowsProtection:
    def _apply(self, value: bytes, context: bytes, *, decrypt: bool) -> bytes:
        if os.name != 'nt':
            raise RuntimeError('本机来源凭据保护需要 Windows DPAPI，不回退为明文')
        if not isinstance(value, bytes) or not 0 < len(value) <= 16384 or not 0 < len(context) <= 1024:
            raise ValueError('Protected credential size invalid')
        crypt = ctypes.WinDLL('crypt32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        inputs, entropy = ctypes.create_string_buffer(value), ctypes.create_string_buffer(context)
        source = _Blob(len(value), ctypes.cast(inputs, ctypes.POINTER(ctypes.c_ubyte)))
        salt = _Blob(len(context), ctypes.cast(entropy, ctypes.POINTER(ctypes.c_ubyte)))
        result = _Blob()
        operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
        operation.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob),
                              ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
        operation.restype = wintypes.BOOL
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        # UI_FORBIDDEN: service/maintenance execution must never open a prompt.
        if not operation(ctypes.byref(source), None, ctypes.byref(salt), None, None, 1, ctypes.byref(result)):
            raise ValueError('本机来源凭据保护失败；不能更换身份或回退明文')
        try:
            if not 0 < result.size <= 16384:
                raise ValueError('Protected credential output exceeds bounds')
            return ctypes.string_at(result.data, result.size)
        finally:
            if result.data:
                ctypes.memset(result.data, 0, result.size)
                kernel.LocalFree(result.data)
            ctypes.memset(inputs, 0, len(inputs))

    def seal(self, value: bytes, context: bytes) -> bytes:
        return self._apply(value, context, decrypt=False)

    def open(self, value: bytes, context: bytes) -> bytes:
        return self._apply(value, context, decrypt=True)
