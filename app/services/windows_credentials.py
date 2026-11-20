"""Защита локальных ключей Windows DPAPI для текущего пользователя."""

import base64
import ctypes
import sys
from ctypes import wintypes


class _Blob(ctypes.Structure):
    _fields_ = [("length", wintypes.DWORD), ("data", ctypes.c_void_p)]


def _transform(data: bytes, *, decrypt: bool) -> bytes:
    if sys.platform != "win32":
        raise OSError("Windows DPAPI is unavailable")
    source_buffer = ctypes.create_string_buffer(data)
    source = _Blob(len(data), ctypes.cast(source_buffer, ctypes.c_void_p))
    target = _Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32")
    release = kernel32.LocalFree
    release.argtypes = [ctypes.c_void_p]
    release.restype = ctypes.c_void_p
    transform = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    transform.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    transform.restype = wintypes.BOOL
    if not transform(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.data, target.length)
    finally:
        release(target.data)


def protect_secret(secret: str) -> str:
    return base64.b64encode(_transform(secret.encode("utf-8"), decrypt=False)).decode("ascii")


def unprotect_secret(protected: str) -> str:
    return _transform(base64.b64decode(protected, validate=True), decrypt=True).decode("utf-8")
