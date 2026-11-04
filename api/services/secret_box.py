"""
Szyfrowanie własnych kluczy LLM organizacji (providers.api_key_encrypted).

Format (identyczny jak gateway/secret_box.py — API szyfruje, bramka odszyfrowuje):
    klucz   = SHA-256(PROVIDER_KEYS_SECRET)              (32 bajty, AES-256)
    zapis   = "v1:" + base64(nonce(12 B) + ciphertext)   (AES-GCM, tag w ciphertext)
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import os
from typing import Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_PREFIX = "v1:"
_NONCE_LEN = 12


class SecretBoxError(Exception):
    """Brak klucza, zły format albo nieudane odszyfrowanie (zły klucz / zmieniony szyfrogram)."""


def _derive_key(secret: Optional[str]) -> bytes:
    if secret is None:
        secret = os.environ.get("PROVIDER_KEYS_SECRET", "")
    if not secret:
        raise SecretBoxError("PROVIDER_KEYS_SECRET nie jest ustawiony")
    return hashlib.sha256(secret.encode("utf-8")).digest()


def is_configured() -> bool:
    return bool(os.environ.get("PROVIDER_KEYS_SECRET", ""))


def encrypt(plaintext: str, secret: Optional[str] = None) -> str:
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(_derive_key(secret)).encrypt(nonce, plaintext.encode("utf-8"), None)
    return _PREFIX + base64.b64encode(nonce + ct).decode("ascii")


def decrypt(token: str, secret: Optional[str] = None) -> str:
    """Odszyfrowanie — API używa go dla klucza organizacji do raportów/klasyfikatora."""
    if not token or not token.startswith(_PREFIX):
        raise SecretBoxError("Nieobsługiwany format zaszyfrowanego klucza")
    try:
        raw = base64.b64decode(token[len(_PREFIX):], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SecretBoxError("Uszkodzony zapis zaszyfrowanego klucza") from exc
    if len(raw) <= _NONCE_LEN + 16:
        raise SecretBoxError("Uszkodzony zapis zaszyfrowanego klucza")
    try:
        plain = AESGCM(_derive_key(secret)).decrypt(raw[:_NONCE_LEN], raw[_NONCE_LEN:], None)
    except InvalidTag as exc:
        raise SecretBoxError("Nie udało się odszyfrować klucza (zły PROVIDER_KEYS_SECRET?)") from exc
    return plain.decode("utf-8")
