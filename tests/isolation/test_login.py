"""Logowanie przy wspólnym e-mailu w dwóch organizacjach."""
from __future__ import annotations

import os
import uuid

import pytest

from conftest import _hash_pw, admin_fetch, auth, login


def test_same_email_password_a_logs_into_a(org_a, org_b):
    r = login(org_a.email, org_a.password)
    assert r.status_code == 200, r.text
    user = r.json()["user"]
    assert user["id"] == org_a.partner_id
    assert user["tenant"]["id"] == org_a.id
    assert user["tenant"]["slug"] == org_a.slug
    assert user["is_super_admin"] is False


def test_same_email_password_b_logs_into_b(org_a, org_b):
    r = login(org_b.email, org_b.password)
    assert r.status_code == 200, r.text
    user = r.json()["user"]
    assert user["id"] == org_b.partner_id
    assert user["tenant"]["id"] == org_b.id


def test_wrong_password_rejected(org_a):
    r = login(org_a.email, "zle-haslo-" + uuid.uuid4().hex)
    assert r.status_code == 401, r.text


def test_token_me_returns_own_tenant(api, org_a, org_b):
    for org in (org_a, org_b):
        r = api.get("/auth/me", headers=auth(org.token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"] == org.partner_id
        assert str(body.get("tenant", {}).get("id", body.get("tenant_id"))) == org.id


def test_same_email_same_password_is_ambiguous(org_a, org_b):
    """Ten sam e-mail i hasło w dwóch organizacjach — logowanie bez subdomeny
    nie może zgadywać organizacji (409), a tym bardziej wybrać „pierwszej z brzegu”."""
    email = f"dup-{uuid.uuid4().hex[:8]}@isolation.test"
    password = "Shared-" + uuid.uuid4().hex
    pw_hash = _hash_pw(password)
    for org in (org_a, org_b):
        admin_fetch(
            """INSERT INTO users (tenant_id, email, full_name, role, status, password_hash)
               VALUES ($1, $2, 'dup', 'associate', 'active', $3) RETURNING id""",
            uuid.UUID(org.id), email, pw_hash)
    r = login(email, password)
    assert r.status_code == 409, r.text


def test_subdomain_login_selects_tenant(org_a, org_b):
    domains = [d.strip() for d in os.environ.get("TENANT_BASE_DOMAINS", "").split(",") if d.strip()]
    if not domains:
        pytest.skip("API nie ma TENANT_BASE_DOMAINS — logowanie przez subdomenę organizacji "
                    "nieaktywne, test subdomen pominięty")
    base = domains[0]
    # Hasło A na subdomenie A → konto A
    r = login(org_a.email, org_a.password, host=f"{org_a.slug}.{base}")
    assert r.status_code == 200, r.text
    assert r.json()["user"]["tenant"]["id"] == org_a.id
    # Hasło B na subdomenie A → odmowa (konto B nie istnieje w organizacji A)
    r = login(org_b.email, org_b.password, host=f"{org_a.slug}.{base}")
    assert r.status_code == 401, r.text
    # Hasło B na subdomenie B → konto B
    r = login(org_b.email, org_b.password, host=f"{org_b.slug}.{base}")
    assert r.status_code == 200, r.text
    assert r.json()["user"]["tenant"]["id"] == org_b.id
