"""
Panel super-admina (/platform/*) i mechanizmy etapu 4: dostęp tylko dla
super-admina, zakładanie / zawieszanie / usuwanie organizacji, wymuszona zmiana
hasła, wejście w kontekst organizacji (token act), szyfrowane klucze providerów,
platform_audit_log niewidoczny dla organizacji, natychmiastowa blokada konta.

Super-admin to partner świeżej organizacji testowej S (is_super_admin ustawiane
SQL-em). Organizacje zakładane przez API mają slug iso-test-p-<losowy> i są
usuwane po module (razem z wpisami platform_audit_log).
"""
from __future__ import annotations

import asyncio
import os
import secrets
import time
import uuid

import asyncpg
import bcrypt
import httpx
import pytest

from conftest import (
    API_URL, SLUG_PREFIX, Org, _create_org, _purge_tenants, _token, admin_fetch, admin_val,
    app_dsn, auth, leaked, login, wait_for,
)

DEMO_TENANT_ID = "d0000000-0000-0000-0000-000000000001"


# ── Fixture ─────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def super_org() -> Org:
    """Organizacja S z partnerem będącym super-adminem platformy."""
    run_id = secrets.token_hex(4)
    org = asyncio.run(_create_org(
        "S", run_id, f"super-{run_id}@isolation.test",
        {"S": f"iso-model-s-{run_id}", "A": f"iso-model-s2-{run_id}"},
        ("pagination.dashboard_top_agents", 9)))
    try:
        admin_fetch("UPDATE users SET is_super_admin = true WHERE id = $1 RETURNING id", uuid.UUID(org.partner_id))
        org.token = _token(org.email, org.password)
        org.admin_token = _token(org.admin_email, org.admin_password)
        yield org
    finally:
        asyncio.run(_purge_tenants("id = $1::uuid", org.id))


@pytest.fixture(scope="module")
def make_tenant(super_org):
    """Fabryka organizacji zakładanych przez POST /platform/tenants (sprzątane po module)."""
    created: list[str] = []

    def _make(**extra) -> dict:
        slug = f"{SLUG_PREFIX}p-{secrets.token_hex(4)}"
        body = {"slug": slug, "name": f"ISO platform {slug}",
                "admin_email": f"admin-{slug}@isolation.test", "admin_full_name": "ISO first admin", **extra}
        with httpx.Client(base_url=API_URL, timeout=60) as c:
            r = c.post("/platform/tenants", headers=auth(super_org.token), json=body)
        assert r.status_code == 201, f"{r.status_code}: {r.text}"
        data = r.json()
        created.append(data["tenant"]["id"])
        return {**data, "slug": slug, "body": body}

    yield _make
    if created:
        asyncio.run(_purge_tenants("id = ANY($1::uuid[])", created))


def _ids(tenant: dict) -> tuple[str, str, str]:
    return tenant["tenant"]["id"], tenant["admin"]["email"], tenant["temporary_password"]


def _tenant_row(tenant_id: str) -> dict:
    return admin_fetch("SELECT * FROM tenants WHERE id = $1", uuid.UUID(tenant_id))[0]


# ── 1. Dostęp do /platform/* tylko dla super-admina ─────────────────────────────

def _platform_calls(org_b: Org) -> list[tuple[str, str, dict | None]]:
    tid, uid = org_b.id, org_b.partner_id
    return [
        ("GET", "/platform/tenants", None),
        ("POST", "/platform/tenants", {"slug": f"{SLUG_PREFIX}p-deny-{secrets.token_hex(3)}", "name": "x",
                                        "admin_email": "x@isolation.test", "admin_full_name": "x"}),
        ("PATCH", f"/platform/tenants/{tid}", {"status": "suspended"}),
        ("DELETE", f"/platform/tenants/{tid}", None),
        ("GET", f"/platform/tenants/{tid}/users", None),
        ("POST", f"/platform/tenants/{tid}/users/{uid}/reset-password", None),
        ("POST", f"/platform/tenants/{tid}/enter", None),
        ("GET", "/platform/audit", None),
    ]


@pytest.mark.parametrize("role", ["partner", "it_admin"])
def test_platform_endpoints_forbidden_for_tenant_admins(api, org_a, org_b, role):
    token = org_a.token if role == "partner" else org_a.admin_token
    before = _tenant_row(org_b.id)
    pw_before = admin_val("SELECT password_hash FROM users WHERE id = $1", uuid.UUID(org_b.partner_id))
    failures = []
    for method, url, body in _platform_calls(org_b):
        r = api.request(method, url, headers=auth(token), json=body)
        if r.status_code != 403:
            failures.append(f"{method} {url} → {r.status_code}: {r.text[:200]}")
    assert not failures, "\n".join(failures)
    assert _tenant_row(org_b.id) == before
    assert admin_val("SELECT password_hash FROM users WHERE id = $1", uuid.UUID(org_b.partner_id)) == pw_before


def test_platform_endpoints_require_token(api, org_b):
    for method, url, body in _platform_calls(org_b):
        r = api.request(method, url, json=body)
        assert r.status_code == 401, f"{method} {url} → {r.status_code}"


# ── 2. Zakładanie organizacji ───────────────────────────────────────────────────

def test_create_tenant(api, super_org, make_tenant):
    t = make_tenant(default_locale="de")
    tid, admin_email, temp_pw = _ids(t)
    assert t["tenant"]["slug"] == t["slug"]
    assert temp_pw and len(temp_pw) >= 12

    row = _tenant_row(tid)
    assert row["status"] == "active" and row["deleted_at"] is None and row["is_demo"] is False

    admins = admin_fetch("SELECT email, role::text AS role, must_change_password, tenant_id::text AS tenant_id "
                         "FROM users WHERE tenant_id = $1", uuid.UUID(tid))
    assert admins == [{"email": admin_email, "role": "partner", "must_change_password": True, "tenant_id": tid}]

    template = admin_fetch(
        "SELECT policy_code FROM policies WHERE tenant_id = $1 AND active AND policy_code IS NOT NULL "
        "AND agent_id IS NULL ORDER BY 1", uuid.UUID(DEMO_TENANT_ID))
    copied = admin_fetch("SELECT policy_code FROM policies WHERE tenant_id = $1 ORDER BY 1", uuid.UUID(tid))
    assert copied == template

    locale = admin_val("SELECT value #>> '{}' FROM app_settings_values WHERE tenant_id = $1 "
                       "AND key = 'i18n.default_locale'", uuid.UUID(tid))
    assert locale == "de"

    audit = wait_for("SELECT actor_user_id::text AS actor FROM platform_audit_log "
                     "WHERE action = 'tenant.create' AND tenant_id = $1", uuid.UUID(tid))
    assert [a["actor"] for a in audit] == [super_org.partner_id]

    listed = api.get("/platform/tenants", headers=auth(super_org.token))
    assert listed.status_code == 200
    assert tid in {x["id"] for x in listed.json()}


@pytest.mark.parametrize("slug", ["app", "www", "api", "Bad_Slug!", "-x"])
def test_create_tenant_invalid_slug(api, super_org, slug):
    r = api.post("/platform/tenants", headers=auth(super_org.token), json={
        "slug": slug, "name": "x", "admin_email": "x@isolation.test", "admin_full_name": "x"})
    assert r.status_code in (400, 422), f"{r.status_code}: {r.text}"
    if slug in ("app", "www", "api"):
        assert r.status_code == 400
    assert admin_val("SELECT count(*) FROM tenants WHERE slug = $1", slug.strip().lower()) == 0


def test_create_tenant_slug_taken(api, super_org, org_a):
    count = admin_val("SELECT count(*) FROM tenants")
    r = api.post("/platform/tenants", headers=auth(super_org.token), json={
        "slug": org_a.slug, "name": "x", "admin_email": "x@isolation.test", "admin_full_name": "x"})
    assert r.status_code == 409, r.text
    assert admin_val("SELECT count(*) FROM tenants") == count


def test_platform_tenant_users_and_reset(api, super_org, make_tenant):
    t = make_tenant()
    tid, admin_email, _ = _ids(t)
    r = api.get(f"/platform/tenants/{tid}/users", headers=auth(super_org.token))
    assert r.status_code == 200, r.text
    assert [u["email"] for u in r.json()] == [admin_email]
    uid = r.json()[0]["id"]
    # Użytkownik innej organizacji pod adresem tej organizacji → 404
    r = api.post(f"/platform/tenants/{tid}/users/{super_org.admin_id}/reset-password",
                 headers=auth(super_org.token))
    assert r.status_code == 404, r.text
    r = api.post(f"/platform/tenants/{tid}/users/{uid}/reset-password", headers=auth(super_org.token))
    assert r.status_code == 200, r.text
    assert login(admin_email, r.json()["temporary_password"]).status_code == 200


# ── 3. Wymuszona zmiana hasła ───────────────────────────────────────────────────

def test_must_change_password_flow(api, gateway, make_tenant):
    t = make_tenant()
    _, admin_email, temp_pw = _ids(t)
    r = login(admin_email, temp_pw)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["must_change_password"] is True
    token = r.json()["access_token"]

    r = api.get("/agents", headers=auth(token))
    assert r.status_code == 403, r.text
    assert r.headers.get("x-govai-error") == "password_change_required"

    me = api.get("/auth/me", headers=auth(token))
    assert me.status_code == 200, me.text
    me_user = me.json().get("user", me.json())
    assert me_user["must_change_password"] is True

    g = gateway.post("/v1/chat/completions", headers=auth(token), json={
        "model": "test", "max_tokens": 8, "messages": [{"role": "user", "content": "x"}]})
    assert g.status_code == 403, g.text
    assert g.headers.get("x-govai-error") == "password_change_required"

    r = api.post("/auth/me/password", headers=auth(token), json={"new_password": "Nowe-Haslo-" + secrets.token_hex(6)})
    assert r.status_code == 200, r.text
    r = api.get("/agents", headers=auth(token))
    assert r.status_code == 200, r.text


# ── 4. Wejście w kontekst organizacji (token act) ───────────────────────────────

def _enter(api, super_org: Org, tenant_id: str) -> httpx.Response:
    return api.post(f"/platform/tenants/{tenant_id}/enter", headers=auth(super_org.token))


ACT_LISTS = {"/agents": "agent_id", "/policies?active_only=false": "policy_id", "/providers": "provider_id"}


def test_enter_sees_only_target_tenant(api, super_org, org_a, org_b):
    r = _enter(api, super_org, org_a.id)
    assert r.status_code == 200, r.text
    act = r.json()["access_token"]
    audit = wait_for("SELECT actor_user_id::text AS actor FROM platform_audit_log "
                     "WHERE action = 'tenant.enter' AND tenant_id = $1", uuid.UUID(org_a.id))
    assert super_org.partner_id in {a["actor"] for a in audit}

    for path, attr in ACT_LISTS.items():
        r = api.get(path, headers=auth(act))
        assert r.status_code == 200, f"{path} → {r.status_code}: {r.text[:300]}"
        assert getattr(org_a, attr) in r.text, f"{path} nie zawiera {attr} organizacji A"
        for other in (org_b, super_org):
            found = leaked(r.text, other)
            assert not found, f"{path} (act A) zawiera dane organizacji {other.label}: {found}"

    me = api.get("/auth/me", headers=auth(act))
    assert me.status_code == 200, me.text


def test_enter_write_lands_in_target_tenant(api, super_org, org_a):
    act = _enter(api, super_org, org_a.id).json()["access_token"]
    r = api.post("/policies", headers=auth(act), json={
        "name": f"{org_a.marker} act policy", "level": "agent", "agent_id": org_a.agent_id,
        "rule_type": "deny", "condition_json": {"keywords": [f"{org_a.keyword}act"]}, "action_json": {},
    })
    assert r.status_code == 201, r.text
    org_a.extra_ids.append(r.json()["id"])
    assert admin_val("SELECT tenant_id::text FROM policies WHERE id = $1", uuid.UUID(r.json()["id"])) == org_a.id


def test_enter_suspended_tenant(api, super_org, make_tenant):
    t = make_tenant()
    tid = t["tenant"]["id"]
    r = _enter(api, super_org, tid)
    assert r.status_code == 200, r.text
    act = r.json()["access_token"]
    assert api.get("/agents", headers=auth(act)).status_code == 200

    r = api.patch(f"/platform/tenants/{tid}", headers=auth(super_org.token), json={"status": "suspended"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "suspended"
    assert api.get("/agents", headers=auth(act)).status_code == 403
    assert _enter(api, super_org, tid).status_code == 400
    assert wait_for("SELECT 1 FROM platform_audit_log WHERE action = 'tenant.update' AND tenant_id = $1",
                    uuid.UUID(tid))


def test_enter_unknown_tenant(api, super_org):
    assert _enter(api, super_org, str(uuid.uuid4())).status_code == 404
    assert _enter(api, super_org, "not-a-uuid").status_code == 404


def test_act_token_after_super_admin_revoked(api, gateway, super_org, org_a):
    act = _enter(api, super_org, org_a.id).json()["access_token"]
    assert api.get("/agents", headers=auth(act)).status_code == 200
    try:
        admin_fetch("UPDATE users SET is_super_admin = false WHERE id = $1 RETURNING id",
                    uuid.UUID(super_org.partner_id))
        r = api.get("/agents", headers=auth(act))
        assert r.status_code in (401, 403), f"{r.status_code}: {r.text[:200]}"
        # Zwykły token tego konta nie daje już dostępu do /platform
        assert api.get("/platform/tenants", headers=auth(super_org.token)).status_code == 403
    finally:
        admin_fetch("UPDATE users SET is_super_admin = true WHERE id = $1 RETURNING id",
                    uuid.UUID(super_org.partner_id))


# ── 5. Zawieszenie / usunięcie organizacji ──────────────────────────────────────

def _base_domain() -> str:
    domains = [d.strip() for d in os.environ.get("TENANT_BASE_DOMAINS", "").split(",") if d.strip()]
    if "localhost" not in domains:
        pytest.skip(f"TENANT_BASE_DOMAINS={domains} bez localhost")
    return "localhost"


def _public(api, slug: str) -> httpx.Response:
    return api.get("/public/tenant", headers={"Host": f"{slug}.{_base_domain()}"})


def test_public_tenant_unknown_and_universal(api):
    base = _base_domain()
    assert api.get("/public/tenant", headers={"Host": base}).status_code == 404
    assert api.get("/public/tenant", headers={"Host": f"app.{base}"}).status_code == 404
    assert _public(api, f"{SLUG_PREFIX}none-{secrets.token_hex(4)}").status_code == 404


def test_suspend_and_delete_tenant(api, super_org, make_tenant):
    t = make_tenant(default_locale="it")
    tid, admin_email, temp_pw = _ids(t)
    slug = t["slug"]

    r = _public(api, slug)
    assert r.status_code == 200, r.text
    assert r.json() == {"slug": slug, "name": t["body"]["name"], "default_locale": "it"}
    assert login(admin_email, temp_pw).status_code == 200
    token = login(admin_email, temp_pw).json()["access_token"]

    r = api.patch(f"/platform/tenants/{tid}", headers=auth(super_org.token), json={"status": "suspended"})
    assert r.status_code == 200, r.text
    assert login(admin_email, temp_pw).status_code in (401, 403)
    assert api.get("/auth/me", headers=auth(token)).status_code in (401, 403)
    assert _public(api, slug).status_code == 404

    r = api.patch(f"/platform/tenants/{tid}", headers=auth(super_org.token), json={"status": "active"})
    assert r.status_code == 200, r.text
    assert _public(api, slug).status_code == 200
    assert login(admin_email, temp_pw).status_code == 200

    r = api.delete(f"/platform/tenants/{tid}", headers=auth(super_org.token))
    assert r.status_code == 200, r.text
    assert _tenant_row(tid)["deleted_at"] is not None
    assert login(admin_email, temp_pw).status_code in (401, 403)
    assert api.get("/auth/me", headers=auth(token)).status_code in (401, 403)
    assert _public(api, slug).status_code == 404
    assert wait_for("SELECT 1 FROM platform_audit_log WHERE action = 'tenant.delete' AND tenant_id = $1",
                    uuid.UUID(tid))
    # Usuniętej nie można wznowić ani usunąć ponownie
    assert api.patch(f"/platform/tenants/{tid}", headers=auth(super_org.token),
                     json={"status": "active"}).status_code == 400
    assert api.delete(f"/platform/tenants/{tid}", headers=auth(super_org.token)).status_code == 400


def test_cannot_delete_demo_or_own_tenant(api, super_org):
    before = admin_fetch("SELECT id, status, deleted_at FROM tenants WHERE id = ANY($1::uuid[]) ORDER BY id",
                         [uuid.UUID(DEMO_TENANT_ID), uuid.UUID(super_org.id)])
    assert api.delete(f"/platform/tenants/{DEMO_TENANT_ID}", headers=auth(super_org.token)).status_code == 400
    assert api.delete(f"/platform/tenants/{super_org.id}", headers=auth(super_org.token)).status_code == 400
    assert api.patch(f"/platform/tenants/{super_org.id}", headers=auth(super_org.token),
                     json={"status": "suspended"}).status_code == 400
    after = admin_fetch("SELECT id, status, deleted_at FROM tenants WHERE id = ANY($1::uuid[]) ORDER BY id",
                        [uuid.UUID(DEMO_TENANT_ID), uuid.UUID(super_org.id)])
    assert after == before


# ── 6. Własne klucze providerów ─────────────────────────────────────────────────

def test_provider_api_key_encrypted_and_isolated(api, org_a, org_b):
    secret = f"sk-iso-{secrets.token_hex(20)}"
    r = api.post("/providers", headers=auth(org_a.token), json={
        "name": f"{org_a.marker} keyed provider", "provider_type": "custom",
        "model_ids": [f"iso-keyed-{org_a.marker}"], "base_url": "http://127.0.0.1:9/v1",
        "api_key": secret,
    })
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    org_a.extra_ids.append(pid)
    assert secret not in r.text
    assert "api_key_encrypted" not in r.json()
    assert r.json()["has_api_key"] is True

    for path in ("/providers", f"/providers/{pid}"):
        g = api.get(path, headers=auth(org_a.token))
        assert g.status_code == 200, g.text
        assert secret not in g.text and "v1:" not in g.text

    stored = admin_val("SELECT api_key_encrypted FROM providers WHERE id = $1", uuid.UUID(pid))
    assert stored.startswith("v1:") and secret not in stored

    lst = api.get("/providers", headers=auth(org_b.token))
    assert lst.status_code == 200 and pid not in lst.text
    assert api.get(f"/providers/{pid}", headers=auth(org_b.token)).status_code in (403, 404)

    # api_key razem z api_key_env → 400; "" usuwa klucz
    bad = api.post("/providers", headers=auth(org_a.token), json={
        "name": "x", "provider_type": "anthropic", "api_key": secret, "api_key_env": "ANTHROPIC_API_KEY"})
    assert bad.status_code == 400, bad.text
    p = api.patch(f"/providers/{pid}", headers=auth(org_a.token), json={"api_key": ""})
    assert p.status_code == 200, p.text
    assert p.json()["has_api_key"] is False
    assert admin_val("SELECT api_key_encrypted FROM providers WHERE id = $1", uuid.UUID(pid)) is None


# ── 7. platform_audit_log a rola aplikacji ──────────────────────────────────────

def _as_app(fn, tenant_id=None, platform=False):
    async def runner():
        conn = await asyncpg.connect(app_dsn())
        try:
            tx = conn.transaction()
            await tx.start()
            try:
                if tenant_id:
                    await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
                if platform:
                    await conn.execute("SELECT set_config('app.platform', 'on', true)")
                return await fn(conn)
            finally:
                await tx.rollback()
        finally:
            await conn.close()
    return asyncio.run(runner())


@pytest.fixture(scope="module")
def platform_audit_row(super_org):
    """Wpis dziennika platformy dotyczący organizacji S (sprzątany z organizacją)."""
    row_id = admin_val(
        "INSERT INTO platform_audit_log (actor_user_id, actor_email, action, tenant_id, details) "
        "VALUES ($1, $2, 'isolation.test', $3, '{}'::jsonb) RETURNING id",
        uuid.UUID(super_org.partner_id), super_org.email, uuid.UUID(super_org.id))
    return row_id


@pytest.mark.parametrize("context", ["tenant", "none"])
def test_platform_audit_invisible_to_tenant(super_org, platform_audit_row, context):
    async def q(conn):
        return await conn.fetchval("SELECT count(*) FROM platform_audit_log")
    assert _as_app(q, tenant_id=super_org.id if context == "tenant" else None) == 0


@pytest.mark.parametrize("context", ["tenant", "platform"])
@pytest.mark.parametrize("stmt", [
    "UPDATE platform_audit_log SET action = 'x' WHERE id = $1",
    "DELETE FROM platform_audit_log WHERE id = $1",
], ids=["update", "delete"])
def test_platform_audit_immutable_for_app(super_org, platform_audit_row, context, stmt):
    async def q(conn):
        await conn.execute(stmt, platform_audit_row)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        _as_app(q, tenant_id=super_org.id if context == "tenant" else None, platform=context == "platform")
    assert admin_val("SELECT action FROM platform_audit_log WHERE id = $1", platform_audit_row) == "isolation.test"


def test_platform_audit_insert_denied_in_tenant_context(super_org):
    async def q(conn):
        await conn.execute("INSERT INTO platform_audit_log (actor_email, action, tenant_id) "
                           "VALUES ('x@isolation.test', 'forged', $1)", uuid.UUID(super_org.id))
    with pytest.raises(asyncpg.PostgresError):
        _as_app(q, tenant_id=super_org.id)


def test_platform_audit_api_lists_entries(api, super_org, platform_audit_row):
    r = api.get("/platform/audit?limit=1000", headers=auth(super_org.token))
    assert r.status_code == 200, r.text
    assert platform_audit_row in {e["id"] for e in r.json()}


# ── 8. Zablokowane konto z ważnym JWT ───────────────────────────────────────────

@pytest.mark.slow
def test_suspended_user_rejected(api, gateway, super_org):
    uid = str(uuid.uuid4())
    email = f"victim-{secrets.token_hex(4)}@isolation.test"
    password = f"Victim-{secrets.token_hex(8)}"
    admin_fetch(
        "INSERT INTO users (id, tenant_id, email, full_name, role, status, password_hash) "
        "VALUES ($1, $2, $3, 'ISO victim', 'partner'::user_role, 'active', $4) RETURNING id",
        uuid.UUID(uid), uuid.UUID(super_org.id), email, bcrypt.hashpw(password.encode(), bcrypt.gensalt(4)).decode())
    token = _token(email, password)

    def call():
        return gateway.post("/v1/chat/completions", headers={
            **auth(token), "X-Agent-ID": super_org.agent_id, "X-Task-ID": f"iso-task-{uuid.uuid4().hex}"},
            json={"model": "test", "max_tokens": 8, "messages": [{"role": "user", "content": "Dzień dobry"}]})

    assert api.get("/agents", headers=auth(token)).status_code == 200
    primed = time.monotonic()
    g = call()   # werdykt konta trafia do cache gatewaya
    assert g.status_code not in (401, 403), f"{g.status_code}: {g.text[:300]}"

    admin_fetch("UPDATE users SET status = 'suspended' WHERE id = $1 RETURNING id", uuid.UUID(uid))
    r = api.get("/agents", headers=auth(token))
    assert r.status_code in (401, 403), f"{r.status_code}: {r.text[:200]}"

    status = None
    while time.monotonic() - primed < 40:
        status = call().status_code
        if status in (401, 403):
            break
        time.sleep(2)
    elapsed = time.monotonic() - primed
    assert status in (401, 403), f"Gateway nadal przyjmuje zablokowane konto po {elapsed:.0f} s ({status})"
    assert elapsed <= 35, f"Gateway odrzucił konto dopiero po {elapsed:.0f} s"
