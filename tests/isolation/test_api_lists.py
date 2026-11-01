"""
API: listy i agregaty — organizacja widzi wyłącznie własne dane (i wiersze
platformy w katalogach), nigdy żadnego identyfikatora drugiej organizacji.
"""
from __future__ import annotations

import pytest

from conftest import auth, leaked

LIST_ENDPOINTS = [
    "/agents",
    "/policies?active_only=false",
    "/providers",
    "/compliance",
    "/audit",
    "/audit/summary",
    "/oversight/pending",
    "/auth/users",
    "/auth/api-keys",
    "/settings",
    "/dashboard/summary",
    "/dashboard/timeline",
    "/reports/enterprise",
]

# Lista → atrybut Org, który MUSI się w niej znaleźć (kontrola, że test nie jest pusty)
OWN_ID_EXPECTED = {
    "/agents": "agent_id",
    "/policies?active_only=false": "policy_id",
    "/providers": "provider_id",
    "/compliance": "requirement_id",
    "/audit": "audit_call_id",
    "/oversight/pending": "oversight_id",
    "/auth/users": "partner_id",
    "/auth/api-keys": "api_key_id",
}


@pytest.mark.parametrize("direction", ["A->B", "B->A"])
@pytest.mark.parametrize("path", LIST_ENDPOINTS)
def test_list_contains_no_foreign_ids(api, orgs, direction, path):
    actor, other = orgs if direction == "A->B" else orgs[::-1]
    r = api.get(path, headers=auth(actor.token))
    assert r.status_code == 200, f"{path} → {r.status_code}: {r.text[:300]}"
    found = leaked(r.text, other)
    assert not found, f"{direction} {path} zawiera dane organizacji {other.label}: {found}"
    attr = OWN_ID_EXPECTED.get(path)
    if attr:
        assert getattr(actor, attr) in r.text, f"{path} nie zawiera własnego {attr} organizacji {actor.label}"


@pytest.mark.parametrize("path,key", [("/providers", "providers"), ("/compliance", "requirements")])
def test_platform_rows_visible_to_both(api, orgs, platform_ids, path, key):
    if not platform_ids[key]:
        pytest.skip(f"Brak wierszy platformy w {key}")
    for org in orgs:
        r = api.get(path, headers=auth(org.token))
        assert r.status_code == 200, r.text
        ids = {str(item["id"]) for item in r.json()}
        missing = set(platform_ids[key]) - ids
        assert not missing, f"Organizacja {org.label} nie widzi wierszy platformy {key}: {missing}"


def test_dashboard_counts_only_own_agents(api, orgs):
    """Każda organizacja ma dokładnie 3 agentów testowych — pulpit nie może
    liczyć agentów innych organizacji (np. ~demo)."""
    for org in orgs:
        r = api.get("/dashboard/summary", headers=auth(org.token))
        assert r.status_code == 200, r.text
        agents = r.json()["agents"]
        total = agents.get("total", agents.get("total_agents"))
        if total is None:
            pytest.skip(f"Nieznany kształt dashboard.agents: {agents}")
        assert int(total) == 3, f"{org.label}: dashboard liczy {total} agentów zamiast 3: {agents}"


def test_enterprise_report_counts_only_own_agents(api, orgs):
    for org in orgs:
        r = api.get("/reports/enterprise", headers=auth(org.token))
        assert r.status_code == 200, r.text
        assert r.json()["agents_count"] == 3, r.json()


def test_pending_oversight_only_own(api, orgs):
    for org in orgs:
        r = api.get("/oversight/pending", headers=auth(org.token))
        assert r.status_code == 200, r.text
        ids = {str(item.get("id")) for item in r.json()}
        assert ids == {org.oversight_id}, f"{org.label}: {ids}"
