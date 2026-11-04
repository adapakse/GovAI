"""
API: zapisy — parametry per organizacja, tenant_id zasobów tworzonych przez API,
katalog platformy tylko do odczytu, /demo/* tylko dla organizacji demo.
"""
from __future__ import annotations

import uuid

import pytest

from conftest import admin_fetch, admin_val, auth, snapshot


def _setting(api, org, key):
    r = api.get(f"/settings/{key}", headers=auth(org.token))
    assert r.status_code == 200, r.text
    return r.json()


def _default(key):
    return admin_val("SELECT value::text FROM app_settings WHERE key = $1", key)


# ── Parametry ────────────────────────────────────────────────────────────────

def test_fixture_overrides_are_tenant_local(api, org_a, org_b):
    a_own = _setting(api, org_a, org_a.setting_key)
    assert a_own["value"] == org_a.setting_value
    b_view = _setting(api, org_b, org_a.setting_key)
    assert str(b_view["value"]) == str(_default(org_a.setting_key)), \
        f"Nadpisanie {org_a.setting_key} z A widoczne w B: {b_view}"

    b_own = _setting(api, org_b, org_b.setting_key)
    assert b_own["value"] == org_b.setting_value
    a_view = _setting(api, org_a, org_b.setting_key)
    assert str(a_view["value"]) == str(_default(org_b.setting_key))


def test_settings_list_uses_own_overrides(api, org_a, org_b):
    def flat(org):
        r = api.get("/settings", headers=auth(org.token))
        assert r.status_code == 200, r.text
        return {s["key"]: s["value"] for items in r.json().values() for s in items}
    a, b = flat(org_a), flat(org_b)
    assert a[org_a.setting_key] == org_a.setting_value
    assert b[org_a.setting_key] != org_a.setting_value
    assert b[org_b.setting_key] == org_b.setting_value
    assert a[org_b.setting_key] != org_b.setting_value


def test_override_via_api_does_not_change_other_tenant(api, org_a, org_b):
    key = "pagination.timeline_default_hours"
    default = _default(key)
    new_value = 13 if str(default) != "13" else 14
    before_b = snapshot(org_b.id)
    r = api.put(f"/settings/{key}", headers=auth(org_a.admin_token), json={"value": new_value})
    assert r.status_code == 200, r.text
    assert _setting(api, org_a, key)["value"] == new_value
    assert str(_setting(api, org_b, key)["value"]) == str(default)
    # W bazie: nadpisanie tylko dla A, wartość domyślna platformy bez zmian
    rows = admin_fetch("SELECT tenant_id::text AS t FROM app_settings_values WHERE key = $1", key)
    assert org_a.id in {x["t"] for x in rows}
    assert org_b.id not in {x["t"] for x in rows}
    assert str(_default(key)) == str(default)
    assert snapshot(org_b.id) == before_b
    # Historia zmian B nie pokazuje zmiany A
    h = api.get(f"/settings/{key}/history", headers=auth(org_b.token))
    assert h.status_code == 200, h.text
    assert org_a.admin_email not in h.text, f"Historia parametru w B ujawnia zmianę A: {h.text[:400]}"
    h = api.get(f"/settings/{key}/history", headers=auth(org_a.token))
    assert org_a.admin_email in h.text


def _platform_setting_put(api, org):
    key = admin_val("SELECT key FROM app_settings WHERE NOT tenant_editable AND editable ORDER BY key LIMIT 1")
    if key is None:
        pytest.skip("Brak parametrów platformy (tenant_editable=false)")
    before = admin_val("SELECT value::text FROM app_settings WHERE key = $1", key)
    overrides_before = admin_fetch("SELECT tenant_id FROM app_settings_values WHERE key = $1", key)
    r = api.put(f"/settings/{key}", headers=auth(org.admin_token), json={"value": before})
    assert admin_val("SELECT value::text FROM app_settings WHERE key = $1", key) == before
    assert admin_fetch("SELECT tenant_id FROM app_settings_values WHERE key = $1", key) == overrides_before
    return r


def test_platform_setting_not_writable_by_tenant_admin(api, org_a):
    """Bezpieczeństwo: parametr platformy nie zmienia się i nie powstaje nadpisanie."""
    r = _platform_setting_put(api, org_a)
    assert not r.is_success, f"PUT parametru platformy przez it_admina organizacji → {r.status_code}"


def test_platform_setting_put_returns_403(api, org_a):
    r = _platform_setting_put(api, org_a)
    assert r.status_code == 403, f"{r.status_code}: {r.text[:300]}"


# ── Zasoby tworzone przez API dostają tenant_id twórcy ───────────────────────

def _tenant_of(table, row_id):
    return admin_val(f"SELECT tenant_id::text FROM {table} WHERE id = $1", uuid.UUID(str(row_id)))


def test_created_policy_belongs_to_creator(api, org_a, org_b):
    r = api.post("/policies", headers=auth(org_a.token), json={
        "name": f"{org_a.marker} api policy", "level": "agent", "agent_id": org_a.agent_id,
        "rule_type": "deny", "condition_json": {"keywords": [f"{org_a.keyword}api"]}, "action_json": {},
    })
    assert r.status_code == 201, r.text
    org_a.extra_ids.append(r.json()["id"])
    assert _tenant_of("policies", r.json()["id"]) == org_a.id


def test_created_provider_belongs_to_creator(api, org_a):
    r = api.post("/providers", headers=auth(org_a.token), json={
        "name": f"{org_a.marker} api provider", "provider_type": "custom",
        "model_ids": [f"iso-api-{org_a.marker}"], "base_url": "http://127.0.0.1:9/v1",
        "active": False,
    })
    assert r.status_code == 201, r.text
    org_a.extra_ids.append(r.json()["id"])
    assert _tenant_of("providers", r.json()["id"]) == org_a.id


def test_created_requirement_belongs_to_creator(api, org_a):
    r = api.post("/compliance", headers=auth(org_a.token), json={
        "risk_level": "minimal", "article_ref": f"Art. {org_a.marker} api",
        "requirement_title": f"{org_a.marker} api requirement", "requirement_text": "x",
    })
    assert r.status_code == 201, r.text
    req_id = r.json()["id"]
    org_a.extra_ids.append(req_id)
    assert _tenant_of("ai_act_requirements", req_id) == org_a.id


def test_created_api_key_belongs_to_creator(api, org_a):
    r = api.post("/auth/api-keys", headers=auth(org_a.admin_token),
                 json={"name": f"{org_a.marker} api key", "agent_id": org_a.agent_id})
    assert r.status_code == 201, r.text
    key_id = r.json().get("id") or r.json().get("key_id")
    assert key_id, r.json()
    org_a.extra_ids.append(key_id)
    assert _tenant_of("api_keys", key_id) == org_a.id


def test_created_user_belongs_to_creator(api, org_a, org_b):
    # Ten sam e-mail co it_admin B — w innej organizacji wolno
    r = api.post("/auth/users", headers=auth(org_a.token), json={
        "email": org_b.admin_email, "full_name": f"{org_a.marker} api user",
        "role": "associate", "password": "Associate-pass-123",
    })
    assert r.status_code == 201, r.text
    user_id = r.json()["id"]
    org_a.extra_ids.append(user_id)
    assert _tenant_of("users", user_id) == org_a.id
    # Konto B o tym e-mailu nietknięte
    assert admin_val("SELECT full_name FROM users WHERE id = $1", uuid.UUID(org_b.admin_id)).startswith(org_b.marker)


def test_created_agent_belongs_to_creator(api, org_a):
    """Rejestracja agenta wywołuje klasyfikację ryzyka (LLM) — przy zaślepce klucza
    może się nie udać; wtedy test jest pomijany, nie zaliczany."""
    r = api.post("/agents", headers=auth(org_a.token), json={
        "name": f"{org_a.marker} api agent", "description": "Asystent do streszczania notatek",
        "owner_name": "x", "owner_email": "x@isolation.test",
    })
    if r.status_code >= 500:
        pytest.skip(f"POST /agents → {r.status_code} (klasyfikacja LLM niedostępna?): {r.text[:200]}")
    assert r.status_code == 201, r.text
    org_a.extra_ids.append(r.json()["id"])
    assert _tenant_of("agents", r.json()["id"]) == org_a.id


# ── Katalog platformy tylko do odczytu ───────────────────────────────────────

def test_platform_provider_read_only(api, org_a, platform_ids):
    if not platform_ids["providers"]:
        pytest.skip("Brak providerów platformy")
    pid = platform_ids["providers"][0]
    before = snapshot(None)
    r = api.get(f"/providers/{pid}", headers=auth(org_a.token))
    assert r.status_code == 200, r.text
    for method, url, body in (
        ("PATCH", f"/providers/{pid}", {"notes": "hacked", "priority": 1}),
        ("PATCH", f"/providers/{pid}/health?healthy=false", None),
        ("DELETE", f"/providers/{pid}", None),
    ):
        for token in (org_a.token, org_a.admin_token):
            r = api.request(method, url, headers=auth(token), json=body)
            assert r.status_code == 403, f"{method} {url} → {r.status_code}: {r.text[:300]}"
    r = api.post("/providers", headers=auth(org_a.token), json={
        "name": f"{org_a.marker} fake platform", "provider_type": "custom", "is_platform": True,
        "base_url": "http://127.0.0.1:9/v1",
    })
    assert r.status_code == 403, r.text
    assert snapshot(None) == before


def test_platform_requirement_read_only(api, org_a, platform_ids):
    if not platform_ids["requirements"]:
        pytest.skip("Brak wymagań platformy")
    rid = platform_ids["requirements"][0]
    before = snapshot(None)
    r = api.put(f"/compliance/{rid}", headers=auth(org_a.token), json={"requirement_title": "hacked"})
    assert r.status_code == 403, r.text
    r = api.delete(f"/compliance/{rid}", headers=auth(org_a.token))
    assert r.status_code == 403, r.text
    r = api.post("/compliance", headers=auth(org_a.token), json={
        "risk_level": "minimal", "article_ref": "x", "requirement_title": f"{org_a.marker} fake",
        "requirement_text": "x", "is_platform": True,
    })
    assert r.status_code == 403, r.text
    assert snapshot(None) == before


# ── /demo/* tylko dla organizacji demonstracyjnej ────────────────────────────

@pytest.mark.parametrize("method,path", [
    ("GET", "/demo/scenarios"),
    ("GET", "/demo/seed/status"),
    ("POST", "/demo/seed"),
    ("POST", "/demo/seed-fleet"),
    ("POST", "/demo/run"),
])
def test_demo_forbidden_for_regular_tenant(api, org_a, method, path):
    before = snapshot(org_a.id)
    r = api.request(method, path, headers=auth(org_a.token), json={} if method == "POST" else None)
    assert r.status_code == 403, f"{method} {path} → {r.status_code}: {r.text[:300]}"
    assert snapshot(org_a.id) == before
