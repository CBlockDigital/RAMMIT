"""Encrypts saved Roblox login cookies with Windows DPAPI.

DPAPI ties the ciphertext to the current Windows user on the current PC, so a copied
Accounts.json is useless anywhere else. Moving RAMMIT to another PC/user means signing in
again - that is the intended trade-off.

On-disk format of an encrypted value:  "dpapi1:" + base64(CryptProtectData(...))
"""
import base64

import win32crypt

Prefix = "dpapi1:"
_Entropy = b"RAMMIT-Accounts-v1"
_CryptProtectUiForbidden = 0x1


class DecryptError(Exception):
    pass


def IsEncrypted(Value):
    return isinstance(Value, str) and Value.startswith(Prefix)


def Encrypt(PlainText):
    Blob = win32crypt.CryptProtectData(PlainText.encode("utf-8"), "RAMMIT account", _Entropy, None, None, _CryptProtectUiForbidden)
    return Prefix + base64.b64encode(Blob).decode("ascii")


def Decrypt(Stored):
    if not IsEncrypted(Stored):
        raise DecryptError("Value is not DPAPI-encrypted.")
    try:
        Blob = base64.b64decode(Stored[len(Prefix):], validate=True)
        _Description, Data = win32crypt.CryptUnprotectData(Blob, _Entropy, None, None, _CryptProtectUiForbidden)
        return Data.decode("utf-8")
    except Exception as Error:
        raise DecryptError(type(Error).__name__) from None
