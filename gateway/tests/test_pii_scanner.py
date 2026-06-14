"""Testy jednostkowe skanera PII."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from pii_scanner import PIIScanner


@pytest.fixture(scope="module")
def scanner():
    return PIIScanner()


def test_no_pii_returns_original(scanner):
    messages = [{"role": "user", "content": "Kiedy zostanie przelana rata kredytu?"}]
    result = scanner.scan(messages)
    assert result.has_pii is False
    assert result.pii_count == 0
    assert result.redacted_messages[0]["content"] == messages[0]["content"]


def test_detects_pesel(scanner):
    messages = [{"role": "user", "content": "PESEL klienta: 90010112345"}]
    result = scanner.scan(messages)
    assert result.has_pii is True
    assert "PL_PESEL" in result.pii_categories
    assert "90010112345" not in result.redacted_messages[0]["content"]


def test_detects_email(scanner):
    messages = [{"role": "user", "content": "Wyślij odpowiedź na adres jan.kowalski@bank.pl"}]
    result = scanner.scan(messages)
    assert result.has_pii is True
    assert "EMAIL_ADDRESS" in result.pii_categories
    assert "jan.kowalski@bank.pl" not in result.redacted_messages[0]["content"]


def test_redacts_multiple_entities(scanner):
    messages = [{
        "role": "user",
        "content": "Klient Jan Kowalski, PESEL 90010112345, email jan@test.pl pyta o kredyt.",
    }]
    result = scanner.scan(messages)
    assert result.has_pii is True
    assert result.pii_count >= 2
    content = result.redacted_messages[0]["content"]
    assert "90010112345" not in content
    assert "jan@test.pl" not in content


def test_preserves_message_role(scanner):
    messages = [
        {"role": "system", "content": "Jesteś asystentem."},
        {"role": "user", "content": "Moje PESEL to 90010112345"},
    ]
    result = scanner.scan(messages)
    assert result.redacted_messages[0]["role"] == "system"
    assert result.redacted_messages[1]["role"] == "user"
