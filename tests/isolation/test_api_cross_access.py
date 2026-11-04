"""
API: token organizacji A na zasobach organizacji B (i odwrotnie) → 404/403,
nigdy 2xx; po każdej próbie zapisu stan danych drugiej organizacji
(sprawdzany SQL-em) jest niezmieniony.
"""
from __future__ import annotations

import pytest

from conftest import auth, leaked, snapshot

# (metoda, ścieżka z polami organizacji-celu, body / params)
CROSS_CALLS = [
    ("GET",    "/agents/{agent_id}", None),
    ("GET",    "/agents/{agent_id}/compliance", None),
    ("GET",    "/agents/{agent_id}/stats", None),
    ("GET",    "/agents/{agent_id}/report", None),
    ("GET",    "/agents/{agent_id}/report/pdf", None),
    ("PATCH",  "/agents/{agent_id}/status", {"status": "suspended"}),
    ("PATCH",  "/agents/{agent_id}/registry", {"version": "6.6.6", "intended_purpose": "hacked"}),
    ("PUT",    "/policies/{policy_id}", {"name": "hacked", "active": False}),
    ("PATCH",  "/policies/{policy_id}/keywords", {"keywords": ["hacked"]}),
    ("PATCH",  "/policies/{policy_id}/toggle", None),
    ("DELETE", "/policies/{policy_id}", None),
    ("GET",    "/providers/{provider_id}", None),
    ("PATCH",  "/providers/{provider_id}", {"name": "hacked", "active": False}),
    ("PATCH",  "/providers/{provider_id}/health?healthy=false", None),
    ("DELETE", "/providers/{provider_id}", None),
    ("PUT",    "/compliance/{requirement_id}", {"requirement_title": "hacked", "active": False}),
    ("DELETE", "/compliance/{requirement_id}", None),
    ("PATCH",  "/auth/users/{partner_id}", {"full_name": "hacked", "status": "suspended"}),
    ("PATCH",  "/auth/users/{admin_id}", {"full_name": "hacked", "role": "reviewer"}),
    ("POST",   "/auth/users/{partner_id}/password", {"new_password": "Hacked-password-123"}),
    ("DELETE", "/auth/api-keys/{api_key_id}", None),
    ("GET",    "/oversight/{oversight_id}", None),
    ("POST",   "/oversight/{oversight_id}/start-review", None),
    ("POST",   "/oversight/{oversight_id}/review", {"action": "approved", "comment": "hacked"}),
    ("GET",    "/audit/{audit_call_id}", None),
]


def _ids(o):
    return {
        "agent_id": o.agent_id, "policy_id": o.policy_id, "provider_id": o.provider_id,
        "requirement_id": o.requirement_id, "partner_id": o.partner_id, "admin_id": o.admin_id,
        "api_key_id": o.api_key_id, "oversight_id": o.oversight_id, "audit_call_id": o.audit_call_id,
    }


@pytest.mark.parametrize("direction", ["A->B", "B->A"])
@pytest.mark.parametrize("method,path,body", CROSS_CALLS, ids=[f"{m} {p}" for m, p, _ in CROSS_CALLS])
def test_cross_tenant_resource_access(api, orgs, direction, method, path, body):
    actor, target = orgs if direction == "A->B" else orgs[::-1]
    before = snapshot(target.id)
    url = path.format(**_ids(target))
    r = api.request(method, url, headers=auth(actor.token), json=body)
    assert r.status_code in (403, 404), (
        f"{direction} {method} {url} → {r.status_code} (oczekiwano 403/404): {r.text[:500]}")
    assert not leaked(r.text, target, url), f"Odpowiedź ujawnia dane {target.label}: {r.text[:500]}"
    assert snapshot(target.id) == before, f"{method} {url} zmienił dane organizacji {target.label}"


@pytest.mark.parametrize("direction", ["A->B", "B->A"])
def test_admin_token_cross_tenant_writes(api, orgs, direction):
    """To samo dla it_admina (rola z prawem do kluczy API, użytkowników i parametrów)."""
    actor, target = orgs if direction == "A->B" else orgs[::-1]
    before = snapshot(target.id)
    calls = [
        ("PATCH", f"/auth/users/{target.partner_id}", {"full_name": "hacked"}),
        ("POST", f"/auth/users/{target.admin_id}/password", {"new_password": "Hacked-password-123"}),
        ("DELETE", f"/auth/api-keys/{target.api_key_id}", None),
        ("PATCH", f"/agents/{target.agent_id}/status", {"status": "retired"}),
        ("PATCH", f"/providers/{target.provider_id}", {"active": False}),
    ]
    for method, url, body in calls:
        r = api.request(method, url, headers=auth(actor.admin_token), json=body)
        assert r.status_code in (403, 404), f"{direction} {method} {url} → {r.status_code}: {r.text[:300]}"
    assert snapshot(target.id) == before


@pytest.mark.parametrize("direction", ["A->B", "B->A"])
def test_api_key_for_foreign_agent_rejected(api, orgs, direction):
    actor, target = orgs if direction == "A->B" else orgs[::-1]
    before_actor, before_target = snapshot(actor.id), snapshot(target.id)
    r = api.post("/auth/api-keys", headers=auth(actor.admin_token),
                 json={"name": f"{actor.marker} cross key", "agent_id": target.agent_id})
    assert r.status_code == 404, r.text
    assert snapshot(actor.id)["api_keys"] == before_actor["api_keys"]
    assert snapshot(target.id) == before_target


@pytest.mark.parametrize("direction", ["A->B", "B->A"])
def test_policy_for_foreign_agent_rejected(api, orgs, direction):
    actor, target = orgs if direction == "A->B" else orgs[::-1]
    before_actor, before_target = snapshot(actor.id), snapshot(target.id)
    r = api.post("/policies", headers=auth(actor.token), json={
        "name": f"{actor.marker} cross policy", "level": "agent", "agent_id": target.agent_id,
        "rule_type": "deny", "condition_json": {"keywords": ["x"]}, "action_json": {},
    })
    assert r.status_code == 404, r.text
    assert snapshot(actor.id)["policies"] == before_actor["policies"]
    assert snapshot(target.id) == before_target


@pytest.mark.parametrize("direction", ["A->B", "B->A"])
def test_agent_filter_with_foreign_agent_id_returns_nothing(api, orgs, direction):
    """Filtry list po agent_id drugiej organizacji nie mogą zwrócić jej danych."""
    actor, target = orgs if direction == "A->B" else orgs[::-1]
    for url in (f"/policies?agent_id={target.agent_id}&active_only=false",
                f"/audit?agent_id={target.agent_id}",
                f"/agents/{target.agent_id}/stats"):
        r = api.get(url, headers=auth(actor.token))
        assert r.status_code in (200, 403, 404), f"{url} → {r.status_code}: {r.text[:300]}"
        assert not leaked(r.text, target, url), f"{url} ujawnia dane {target.label}: {r.text[:500]}"


@pytest.mark.parametrize("direction", ["A->B", "B->A"])
def test_oversight_history_with_foreign_agent_id(api, orgs, direction):
    actor, target = orgs if direction == "A->B" else orgs[::-1]
    url = f"/oversight/history?agent_id={target.agent_id}"
    r = api.get(url, headers=auth(actor.token))
    assert r.status_code == 200, f"{url} → {r.status_code}: {r.text[:300]}"
    assert not leaked(r.text, target, url)
