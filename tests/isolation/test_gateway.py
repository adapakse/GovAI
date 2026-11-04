"""
Gateway (http://gateway:8001/v1/chat/completions) i WebSocket live-feed API:
klucze, agenci, polityki, providerzy i zdarzenia nie przechodzą między organizacjami.

Lokalny klucz Anthropic to zaślepka — wywołanie dozwolone kończy się błędem modelu
(5xx), co wystarcza: liczy się, że NIE jest to 401/403 i że wpis audytu trafia
do właściwej organizacji.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid

import pytest
import websockets

from conftest import WS_URL, admin_fetch, auth, snapshot, wait_for

AUDIT_BY_TASK = "SELECT tenant_id::text AS tenant_id, agent_id::text AS agent_id, event_type, " \
                "policy_result::text AS policy_result, policy_id, provider_id::text AS provider_id " \
                "FROM audit_log WHERE task_id = $1"


def _call(gateway, *, key=None, token=None, agent_id=None, text="Dzień dobry, streść proszę notatkę."):
    task_id = f"iso-task-{uuid.uuid4().hex}"
    headers = {"X-Task-ID": task_id}
    if key:
        headers["X-API-Key"] = key
    if token:
        headers.update(auth(token))
    if agent_id:
        headers["X-Agent-ID"] = agent_id
    r = gateway.post("/v1/chat/completions", headers=headers, json={
        "model": "test", "max_tokens": 8, "messages": [{"role": "user", "content": text}],
    })
    return r, task_id


def _audit(task_id, expect=True):
    return wait_for(AUDIT_BY_TASK, task_id) if expect else admin_fetch(AUDIT_BY_TASK, task_id)


# ── Klucz API ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("direction", ["A->B", "B->A"])
def test_api_key_with_foreign_agent_forbidden(gateway, orgs, direction):
    actor, other = orgs if direction == "A->B" else orgs[::-1]
    before = snapshot(other.id)
    r, task = _call(gateway, key=actor.api_key, agent_id=other.agent_id)
    assert r.status_code == 403, f"{r.status_code}: {r.text[:300]}"
    time.sleep(1)
    assert {row["tenant_id"] for row in _audit(task, expect=False)} <= {actor.id}
    assert snapshot(other.id)["audit_log"] == before["audit_log"]


def test_api_key_with_other_own_agent_forbidden(gateway, org_a):
    """Klucz przypięty do agenta A działa tylko za tego agenta (także w obrębie organizacji)."""
    r, _ = _call(gateway, key=org_a.api_key, agent_id=org_a.agent_own_model_id)
    assert r.status_code == 403, r.text


@pytest.mark.parametrize("explicit_agent", [True, False], ids=["X-Agent-ID", "agent-z-klucza"])
def test_api_key_with_own_agent_allowed(gateway, org_a, explicit_agent):
    r, task = _call(gateway, key=org_a.api_key, agent_id=org_a.agent_id if explicit_agent else None)
    assert r.status_code not in (401, 403), f"{r.status_code}: {r.text[:300]}"
    rows = _audit(task)
    assert rows, "Brak wpisu audytu dla wywołania"
    assert all(row["tenant_id"] == org_a.id and row["agent_id"] == org_a.agent_id for row in rows), rows


def test_unknown_key_rejected(gateway, org_a):
    r, _ = _call(gateway, key=org_a.api_key + "x", agent_id=org_a.agent_id)
    assert r.status_code == 401, r.text


# ── JWT ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("direction", ["A->B", "B->A"])
def test_jwt_with_foreign_agent_forbidden(gateway, orgs, direction):
    actor, other = orgs if direction == "A->B" else orgs[::-1]
    before = snapshot(other.id)
    r, task = _call(gateway, token=actor.token, agent_id=other.agent_id)
    assert r.status_code == 403, f"{r.status_code}: {r.text[:300]}"
    assert other.agent_name not in r.text
    time.sleep(1)
    assert {row["tenant_id"] for row in _audit(task, expect=False)} <= {actor.id}
    assert snapshot(other.id)["audit_log"] == before["audit_log"]


def test_jwt_with_own_agent_allowed(gateway, org_b):
    r, task = _call(gateway, token=org_b.token, agent_id=org_b.agent_id)
    assert r.status_code not in (401, 403), f"{r.status_code}: {r.text[:300]}"
    rows = _audit(task)
    assert rows and all(row["tenant_id"] == org_b.id for row in rows), rows


# ── Polityki ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("direction", ["A->B", "B->A"])
def test_foreign_policy_keyword_does_not_block(gateway, orgs, direction):
    actor, other = orgs if direction == "A->B" else orgs[::-1]
    r, task = _call(gateway, key=actor.api_key, text=f"Proszę o analizę: {other.keyword}")
    assert r.status_code not in (401, 403), \
        f"Słowo kluczowe polityki {other.label} zablokowało {actor.label}: {r.status_code} {r.text[:300]}"
    rows = _audit(task)
    assert rows and all(row["tenant_id"] == actor.id for row in rows), rows
    assert all(row["policy_result"] != "blocked" for row in rows), rows
    assert all(row["policy_id"] != other.policy_code for row in rows), rows


@pytest.mark.parametrize("label", ["A", "B"])
def test_own_policy_keyword_blocks(gateway, orgs, label):
    """Kontrola pozytywna: własna polityka organizacji działa."""
    org = orgs[0] if label == "A" else orgs[1]
    r, task = _call(gateway, key=org.api_key, text=f"Tekst z {org.keyword} w środku")
    assert r.status_code == 403, f"{r.status_code}: {r.text[:300]}"
    rows = _audit(task)
    assert rows and rows[0]["tenant_id"] == org.id
    assert rows[0]["policy_result"] == "blocked" and rows[0]["policy_id"] == org.policy_code, rows


# ── Providerzy organizacji ───────────────────────────────────────────────────

@pytest.mark.parametrize("direction", ["A->B", "B->A"])
def test_foreign_tenant_provider_never_selected(gateway, orgs, direction):
    """Agent z modelem, który obsługuje wyłącznie provider DRUGIEJ organizacji →
    brak dostępnego providera (503), a nie wywołanie cudzego providera."""
    actor, other = orgs if direction == "A->B" else orgs[::-1]
    r, task = _call(gateway, token=actor.token, agent_id=actor.agent_foreign_model_id)
    assert r.status_code == 503, f"{r.status_code}: {r.text[:300]}"
    rows = _audit(task)
    assert rows and all(row["tenant_id"] == actor.id for row in rows), rows
    assert all(row["provider_id"] != other.provider_id for row in rows), rows
    assert rows[0]["event_type"] == "no_eligible_provider", rows


@pytest.mark.parametrize("label", ["A", "B"])
def test_own_tenant_provider_selected(gateway, orgs, label):
    """Kontrola pozytywna: własny provider organizacji jest wybierany (jego base_url
    jest nieosiągalny, więc wywołanie kończy się błędem modelu, nie 503)."""
    org = orgs[0] if label == "A" else orgs[1]
    r, task = _call(gateway, token=org.token, agent_id=org.agent_own_model_id)
    assert r.status_code not in (401, 403, 503), f"{r.status_code}: {r.text[:300]}"
    rows = _audit(task)
    assert rows and all(row["tenant_id"] == org.id for row in rows), rows
    assert all(row["event_type"] != "no_eligible_provider" for row in rows), rows


# ── WebSocket live-feed ──────────────────────────────────────────────────────

async def _collect(ws, sink: list, stop: asyncio.Event):
    while not stop.is_set():
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=0.2)
        except asyncio.TimeoutError:
            continue
        except websockets.ConnectionClosed:
            return
        sink.append(json.loads(msg))


def test_live_feed_isolated(gateway, org_a, org_b):
    async def scenario():
        received = {"A": [], "B": []}
        stop = asyncio.Event()
        async with websockets.connect(f"{WS_URL}/ws/live-feed?token={org_a.token}") as ws_a, \
                websockets.connect(f"{WS_URL}/ws/live-feed?token={org_b.token}") as ws_b:
            tasks = [asyncio.create_task(_collect(ws_a, received["A"], stop)),
                     asyncio.create_task(_collect(ws_b, received["B"], stop))]
            await asyncio.sleep(1.0)  # subskrypcja Redis po accept()
            # Wywołanie kluczem B zablokowane polityką B → zdarzenie audit:blocked w B
            r, _ = await asyncio.to_thread(
                _call, gateway, key=org_b.api_key, text=f"Zdarzenie {org_b.keyword}")
            assert r.status_code == 403, r.text
            await asyncio.sleep(3.0)
            stop.set()
            await asyncio.gather(*tasks)
        return received

    received = asyncio.run(scenario())
    b_events = [e for e in received["B"] if (e.get("payload") or {}).get("agent_id") == org_b.agent_id]
    assert b_events, f"B nie dostał własnego zdarzenia: {received['B']}"
    assert any(e.get("type") == "audit:blocked" for e in b_events), b_events
    leaked_to_a = [e for e in received["A"] if org_b.agent_id in json.dumps(e) or org_b.marker in json.dumps(e)]
    assert not leaked_to_a, f"A dostał zdarzenie organizacji B: {leaked_to_a}"
    assert not received["A"], f"A dostał zdarzenia, choć nic nie robił: {received['A']}"


def test_live_feed_rejects_invalid_token():
    async def scenario():
        try:
            async with websockets.connect(f"{WS_URL}/ws/live-feed?token=invalid") as ws:
                await asyncio.wait_for(ws.recv(), timeout=3)
        except (websockets.ConnectionClosed, websockets.InvalidStatus, websockets.InvalidHandshake):
            return True
        return False
    assert asyncio.run(scenario()), "WebSocket przyjął nieprawidłowy token"
