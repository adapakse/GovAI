"""Testy jednostkowe secret_box (odszyfrowanie własnych kluczy LLM organizacji)."""
import base64
import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import secret_box
from models import ProviderRecord

SECRET = "test-provider-keys-secret"


def _reference_encrypt(plaintext: str, secret: str) -> str:
    """Niezależna implementacja formatu z API: "v1:" + base64(nonce + ciphertext),
    klucz SHA-256(secret), AES-GCM z 12-bajtowym nonce."""
    key = hashlib.sha256(secret.encode("utf-8")).digest()
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return "v1:" + base64.b64encode(nonce + ct).decode("ascii")


def test_decrypt_reference_ciphertext():
    token = _reference_encrypt("sk-ant-test-123", SECRET)
    assert secret_box.decrypt(token, SECRET) == "sk-ant-test-123"


def test_roundtrip_unicode():
    token = secret_box.encrypt("klucz-zażółć-🔑", SECRET)
    assert token.startswith("v1:")
    assert secret_box.decrypt(token, SECRET) == "klucz-zażółć-🔑"


def test_nonce_is_random():
    assert secret_box.encrypt("x", SECRET) != secret_box.encrypt("x", SECRET)


def test_wrong_key_fails():
    token = _reference_encrypt("sk-test", SECRET)
    with pytest.raises(secret_box.SecretBoxError):
        secret_box.decrypt(token, "inny-sekret")


def test_tampered_ciphertext_fails():
    raw = bytearray(base64.b64decode(_reference_encrypt("sk-test", SECRET)[3:]))
    raw[-1] ^= 0x01
    with pytest.raises(secret_box.SecretBoxError):
        secret_box.decrypt("v1:" + base64.b64encode(bytes(raw)).decode(), SECRET)


@pytest.mark.parametrize("token", ["", "sk-plain", "v2:AAAA", "v1:%%%", "v1:" + base64.b64encode(b"short").decode()])
def test_bad_format_fails(token):
    with pytest.raises(secret_box.SecretBoxError):
        secret_box.decrypt(token, SECRET)


def test_secret_from_env(monkeypatch):
    monkeypatch.setenv("PROVIDER_KEYS_SECRET", SECRET)
    assert secret_box.decrypt(_reference_encrypt("sk-env", SECRET)) == "sk-env"


def test_missing_secret_fails(monkeypatch):
    monkeypatch.delenv("PROVIDER_KEYS_SECRET", raising=False)
    with pytest.raises(secret_box.SecretBoxError):
        secret_box.decrypt(_reference_encrypt("sk-env", SECRET))


def _provider(**kw):
    base = dict(id="p", name="p", provider_type="anthropic", model_ids=[],
                max_data_sensitivity="internal", priority=1)
    base.update(kw)
    return ProviderRecord(**base)


def test_tenant_provider_uses_own_key_even_with_base_url():
    p = _provider(tenant_id="t1", own_api_key="sk-own", base_url="https://llm.example")
    assert p.resolve_api_key() == "sk-own"
    assert "sk-own" not in repr(p)


def test_platform_provider_ignores_own_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-platform")
    p = _provider(own_api_key="sk-own", api_key_env="ANTHROPIC_API_KEY")
    assert p.resolve_api_key() == "sk-platform"
    # provider platformy z base_url nie dostaje klucza z env
    assert _provider(api_key_env="ANTHROPIC_API_KEY", base_url="https://x").resolve_api_key() is None
