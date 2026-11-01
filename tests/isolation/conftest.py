"""
Wspólne fixture testów izolacji organizacji (multitenancy).

Na sesję powstają dwie świeże organizacje A i B (SQL jako superużytkownik govai,
który omija RLS), każda z kompletem danych: partner + it_admin, agenci, polityka
deny ze słowem kluczowym, klucz API przypięty do agenta, własne wymaganie AI Act,
własny provider, nadpisanie parametru, zadanie nadzoru i wpis audytu.
Partner A i partner B mają TEN SAM e-mail (różne hasła). Po sesji wszystko jest
usuwane (audit_log — w trybie platformy z app.audit_purge).

Testy są synchroniczne (httpx.Client); dostęp do bazy przez asyncio.run(asyncpg)
— bez współdzielonej pętli zdarzeń między testami.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import asyncpg
import bcrypt
import httpx
import pytest

API_URL = os.environ.get("GOVAI_API_URL", "http://api:8000")
GATEWAY_URL = os.environ.get("GOVAI_GATEWAY_URL", "http://gateway:8001")
WS_URL = os.environ.get("GOVAI_WS_URL", API_URL.replace("http", "ws", 1))
DB_HOST = os.environ.get("GOVAI_DB_HOST", "postgres")
DB_PORT = int(os.environ.get("GOVAI_DB_PORT", "5432"))
DB_NAME = os.environ.get("GOVAI_DB_NAME", "govai")
DB_ADMIN_USER = os.environ.get("GOVAI_DB_USER", "govai")
DB_APP_USER = os.environ.get("GOVAI_DB_APP_USER", "govai_app")

SLUG_PREFIX = "iso-test-"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# Tabele z danymi organizacji (tenant_id) — kolejność usuwania przy sprzątaniu
TENANT_TABLES_DELETE_ORDER = [
    "audit_log", "oversight_queue", "api_keys", "policies", "refresh_tokens",
    "app_settings_values", "app_settings_audit", "providers", "ai_act_requirements",
    "agents", "users",
]
# Tabele porównywane przed/po próbach zapisu z obcej organizacji. Kolumny
# zmieniane przez procesy tła (health check, ostatnie użycie) są pomijane.
SNAPSHOT_TABLES = {
    "agents": "",
    "policies": "",
    "providers": " - 'is_healthy' - 'last_health_check_at'",
    "ai_act_requirements": "",
    "users": "",
    "api_keys": " - 'last_used_at'",
    "oversight_queue": "",
    "app_settings_values": "",
    "audit_log": "",
}


def _dsn(user: str, password_env: str) -> str:
    password = os.environ.get(password_env)
    if not password:
        pytest.exit(f"Brak zmiennej {password_env} (uruchamiaj przez tests/isolation/run.sh)", returncode=2)
    return f"postgresql://{user}:{password}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


def admin_dsn() -> str:
    return _dsn(DB_ADMIN_USER, "GOVAI_DB_PASSWORD")


def app_dsn() -> str:
    return _dsn(DB_APP_USER, "GOVAI_DB_APP_PASSWORD")


# ── Baza (superużytkownik — tylko przygotowanie danych i weryfikacja) ────────

async def _admin_fetch(sql: str, *args: Any) -> list[dict]:
    conn = await asyncpg.connect(admin_dsn())
    try:
        return [dict(r) for r in await conn.fetch(sql, *args)]
    finally:
        await conn.close()


def admin_fetch(sql: str, *args: Any) -> list[dict]:
    return asyncio.run(_admin_fetch(sql, *args))


def admin_val(sql: str, *args: Any) -> Any:
    rows = admin_fetch(sql, *args)
    if not rows:
        return None
    return next(iter(rows[0].values()))


def wait_for(sql: str, *args: Any, timeout: float = 8.0) -> list[dict]:
    """Czeka, aż zapytanie zwróci wiersze (np. wpis audytu zapisywany asynchronicznie)."""
    deadline = time.monotonic() + timeout
    while True:
        rows = admin_fetch(sql, *args)
        if rows or time.monotonic() > deadline:
            return rows
        time.sleep(0.3)


def snapshot(tenant_id: Optional[str]) -> dict[str, list[str]]:
    """Stan wierszy organizacji (albo wierszy platformy dla tenant_id=None)."""
    result = {}
    for table, minus in SNAPSHOT_TABLES.items():
        if tenant_id is None:
            if table not in ("providers", "ai_act_requirements"):
                continue
            where, args = "tenant_id IS NULL", ()
        else:
            where, args = "tenant_id = $1", (uuid.UUID(tenant_id),)
        rows = admin_fetch(
            f"SELECT (to_jsonb(x){minus})::text AS j FROM {table} x WHERE {where} ORDER BY 1", *args)
        result[table] = [r["j"] for r in rows]
    return result


# ── Dane organizacji ──────────────────────────────────────────────────────────

@dataclass
class Org:
    label: str                      # "A" / "B"
    id: str
    slug: str
    marker: str                     # unikalny napis w nazwach zasobów organizacji
    email: str                      # e-mail partnera (wspólny dla A i B)
    password: str
    partner_id: str
    admin_email: str
    admin_password: str
    admin_id: str
    agent_id: str                   # agent z modelem platformy
    agent_name: str
    agent_own_model_id: str         # agent z modelem własnego providera organizacji
    agent_foreign_model_id: str     # agent z modelem providera DRUGIEJ organizacji
    policy_id: str
    policy_code: str
    keyword: str
    api_key: str
    api_key_id: str
    requirement_id: str
    provider_id: str
    provider_model: str
    oversight_id: str
    audit_id: str
    audit_call_id: str
    setting_key: str
    setting_value: int
    token: str = ""
    admin_token: str = ""
    extra_ids: list[str] = field(default_factory=list)

    def secret_ids(self) -> set[str]:
        """Identyfikatory i napisy, które NIGDY nie mogą pojawić się w odpowiedzi
        dla drugiej organizacji (e-mail jest wspólny — celowo pominięty)."""
        return {
            self.id, self.slug, self.marker, self.partner_id, self.admin_id, self.admin_email,
            self.agent_id, self.agent_own_model_id, self.agent_foreign_model_id,
            self.policy_id, self.policy_code, self.keyword, self.api_key_id, self.api_key[:16],
            self.requirement_id, self.provider_id, self.oversight_id,
            self.audit_id, self.audit_call_id, *self.extra_ids,
        }


def _hash_pw(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(4)).decode()


async def _create_org(label: str, run_id: str, shared_email: str, provider_models: dict[str, str],
                      setting: tuple[str, int]) -> Org:
    other = "B" if label == "A" else "A"
    lo = label.lower()
    marker = f"ISO{label}{run_id}"
    tenant_id = str(uuid.uuid4())
    slug = f"{SLUG_PREFIX}{lo}-{run_id}"
    password = f"Pass-{label}-{secrets.token_hex(8)}"
    admin_password = f"Admin-{label}-{secrets.token_hex(8)}"
    admin_email = f"itadmin-{lo}-{run_id}@isolation.test"
    partner_id, admin_id = str(uuid.uuid4()), str(uuid.uuid4())
    agent_id, agent_own, agent_foreign = (str(uuid.uuid4()) for _ in range(3))
    policy_id, requirement_id, provider_id = (str(uuid.uuid4()) for _ in range(3))
    api_key_id, oversight_id, audit_id, audit_call_id = (str(uuid.uuid4()) for _ in range(4))
    keyword = f"isokw{lo}{run_id}"
    policy_code = f"ISO-{label}-{run_id}"
    api_key = f"govai_iso_{lo}_{secrets.token_hex(24)}"
    agent_name = f"{marker} agent"

    conn = await asyncpg.connect(admin_dsn())
    try:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO tenants (id, slug, name, is_demo) VALUES ($1, $2, $3, false)",
                tenant_id, slug, f"{marker} organizacja")
            for uid, email, name, role, pw in (
                (partner_id, shared_email, f"{marker} partner", "partner", password),
                (admin_id, admin_email, f"{marker} it admin", "it_admin", admin_password),
            ):
                await conn.execute(
                    """INSERT INTO users (id, tenant_id, email, full_name, role, status, password_hash)
                       VALUES ($1, $2, $3, $4, $5::user_role, 'active', $6)""",
                    uid, tenant_id, email, name, role, _hash_pw(pw))
            for aid, name, model in (
                (agent_id, agent_name, DEFAULT_MODEL),
                (agent_own, f"{marker} agent own model", provider_models[label]),
                (agent_foreign, f"{marker} agent foreign model", provider_models[other]),
            ):
                await conn.execute(
                    """INSERT INTO agents (id, tenant_id, name, description, owner_name, owner_email,
                                           risk_level, status, requires_oversight, model_id, created_by)
                       VALUES ($1, $2, $3, 'Agent testu izolacji', $4, $5, 'minimal', 'active', false, $6, $7)""",
                    aid, tenant_id, name, f"{marker} owner", shared_email, model, partner_id)
            await conn.execute(
                """INSERT INTO policies (id, tenant_id, name, level, rule_type, condition_json,
                                         action_json, priority, policy_code)
                   VALUES ($1, $2, $3, 'org', 'deny', $4::jsonb, $5::jsonb, 1, $6)""",
                policy_id, tenant_id, f"{marker} policy",
                json.dumps({"keywords": [keyword]}),
                json.dumps({"reason": f"{marker} blocked"}), policy_code)
            await conn.execute(
                """INSERT INTO api_keys (id, tenant_id, name, key_hash, key_prefix, created_by, agent_id)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                api_key_id, tenant_id, f"{marker} key", hashlib.sha256(api_key.encode()).hexdigest(),
                api_key[:12], admin_id, agent_id)
            await conn.execute(
                """INSERT INTO ai_act_requirements (id, tenant_id, risk_level, article_ref,
                                                    requirement_title, requirement_text, sort_order)
                   VALUES ($1, $2, 'minimal', $3, $4, 'Wymaganie testu izolacji', 999)""",
                requirement_id, tenant_id, f"Art. {marker}", f"{marker} requirement")
            await conn.execute(
                """INSERT INTO providers (id, tenant_id, name, provider_type, model_ids, base_url,
                                         max_data_sensitivity, active, is_healthy, priority)
                   VALUES ($1, $2, $3, 'custom', $4, 'http://127.0.0.1:9/v1', 'privileged', true, true, 1)""",
                provider_id, tenant_id, f"{marker} provider", [provider_models[label]])
            await conn.execute(
                """INSERT INTO app_settings_values (tenant_id, key, value, updated_by)
                   VALUES ($1, $2, $3::jsonb, 'isolation-test')""",
                tenant_id, setting[0], json.dumps(setting[1]))
            await conn.execute(
                """INSERT INTO oversight_queue (id, tenant_id, agent_id, task_id, decision_type,
                                                agent_decision, status, ttl_expires_at)
                   VALUES ($1, $2, $3, $4, 'test', $5, 'pending', NOW() + interval '1 hour')""",
                oversight_id, tenant_id, agent_id, f"{marker}-task", f"{marker} decision")
            await conn.execute(
                """INSERT INTO audit_log (id, call_id, tenant_id, agent_id, agent_name, task_id,
                                          event_type, policy_result, model_used, metadata)
                   VALUES ($1, $2, $3, $4, $5, $6, 'call_completed', 'allowed', $7, $8::jsonb)""",
                audit_id, audit_call_id, tenant_id, agent_id, agent_name, f"{marker}-task",
                DEFAULT_MODEL, json.dumps({"isolation_test": marker}))
    finally:
        await conn.close()

    return Org(
        label=label, id=tenant_id, slug=slug, marker=marker, email=shared_email, password=password,
        partner_id=partner_id, admin_email=admin_email, admin_password=admin_password, admin_id=admin_id,
        agent_id=agent_id, agent_name=agent_name, agent_own_model_id=agent_own,
        agent_foreign_model_id=agent_foreign, policy_id=policy_id, policy_code=policy_code,
        keyword=keyword, api_key=api_key, api_key_id=api_key_id, requirement_id=requirement_id,
        provider_id=provider_id, provider_model=provider_models[label], oversight_id=oversight_id,
        audit_id=audit_id, audit_call_id=audit_call_id, setting_key=setting[0], setting_value=setting[1],
    )


async def _purge_tenants(where_sql: str, *args: Any) -> None:
    """Usuwa organizacje testowe z wszystkimi danymi. audit_log jest niezmienny —
    usunięcie wymaga trybu platformy + app.audit_purge w tej samej transakcji."""
    conn = await asyncpg.connect(admin_dsn())
    try:
        async with conn.transaction():
            ids = [r["id"] for r in await conn.fetch(f"SELECT id FROM tenants WHERE {where_sql}", *args)]
            if not ids:
                return
            await conn.execute("SELECT set_config('app.platform', 'on', true), "
                               "set_config('app.audit_purge', 'on', true)")
            for table in TENANT_TABLES_DELETE_ORDER:
                await conn.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1::uuid[])", ids)
            await conn.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", ids)
    finally:
        await conn.close()


def login(email: str, password: str, host: Optional[str] = None) -> httpx.Response:
    headers = {"Host": host} if host else {}
    with httpx.Client(base_url=API_URL, timeout=30) as c:
        return c.post("/auth/login", json={"email": email, "password": password}, headers=headers)


def _token(email: str, password: str) -> str:
    r = login(email, password)
    assert r.status_code == 200, f"Logowanie {email} nieudane: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def orgs():
    run_id = secrets.token_hex(4)
    shared_email = f"partner-{run_id}@isolation.test"
    provider_models = {"A": f"iso-model-a-{run_id}", "B": f"iso-model-b-{run_id}"}
    # Pozostałości po przerwanych uruchomieniach (starsze niż godzina)
    asyncio.run(_purge_tenants("slug LIKE $1 AND created_at < NOW() - interval '1 hour'", SLUG_PREFIX + "%"))
    created: list[str] = []
    try:
        a = asyncio.run(_create_org("A", run_id, shared_email, provider_models, ("oversight.history_limit", 111)))
        created.append(a.id)
        b = asyncio.run(_create_org("B", run_id, shared_email, provider_models, ("pagination.dashboard_top_agents", 7)))
        created.append(b.id)
        for o in (a, b):
            o.token = _token(o.email, o.password)
            o.admin_token = _token(o.admin_email, o.admin_password)
        yield a, b
    finally:
        if created:
            asyncio.run(_purge_tenants("id = ANY($1::uuid[])", created))


@pytest.fixture(scope="session")
def org_a(orgs) -> Org:
    return orgs[0]


@pytest.fixture(scope="session")
def org_b(orgs) -> Org:
    return orgs[1]


@pytest.fixture(scope="session")
def platform_ids() -> dict[str, list[str]]:
    return {
        "providers": [str(r["id"]) for r in admin_fetch("SELECT id FROM providers WHERE tenant_id IS NULL")],
        "requirements": [str(r["id"]) for r in admin_fetch(
            "SELECT id FROM ai_act_requirements WHERE tenant_id IS NULL")],
    }


@pytest.fixture(scope="session")
def api() -> httpx.Client:
    with httpx.Client(base_url=API_URL, timeout=60) as c:
        yield c


@pytest.fixture(scope="session")
def gateway() -> httpx.Client:
    with httpx.Client(base_url=GATEWAY_URL, timeout=120) as c:
        yield c


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def leaked(text: str, other: Org, request_url: str = "") -> list[str]:
    """Identyfikatory drugiej organizacji obecne w treści odpowiedzi. Identyfikator,
    który klient sam podał w URL (np. echo w komunikacie 404), nie jest wyciekiem."""
    lowered = text.lower()
    url = request_url.lower()
    return sorted(s for s in other.secret_ids() if s and s.lower() in lowered and s.lower() not in url)
