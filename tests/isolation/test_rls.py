"""
Baza: Row Level Security dla roli aplikacji govai_app (bez superużytkownika).
Każdy test działa w transakcji wycofywanej na końcu — nic nie zostaje w bazie.
"""
from __future__ import annotations

import asyncio
import uuid

import asyncpg
import pytest

from conftest import app_dsn


def in_tx(fn, tenant_id=None, platform=False):
    """Uruchamia fn(conn) jako govai_app w transakcji (z kontekstem organizacji
    albo platformy, albo bez kontekstu) i zawsze ją wycofuje."""
    async def runner():
        conn = await asyncpg.connect(app_dsn())
        result = None
        try:
            tx = conn.transaction()
            await tx.start()
            try:
                if tenant_id:
                    await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
                if platform:
                    await conn.execute("SELECT set_config('app.platform', 'on', true)")
                result = await fn(conn)
            finally:
                await tx.rollback()
        finally:
            await conn.close()
        return result
    return asyncio.run(runner())


def test_connected_as_non_superuser():
    async def q(conn):
        return await conn.fetchrow(
            "SELECT current_user AS u, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
    row = in_tx(q)
    assert row["u"] == "govai_app"
    assert row["rolsuper"] is False and row["rolbypassrls"] is False


@pytest.mark.parametrize("table", ["agents", "audit_log", "users", "policies", "api_keys",
                                   "oversight_queue", "refresh_tokens", "app_settings_values", "tenants"])
def test_no_context_sees_nothing(orgs, table):
    async def q(conn):
        return await conn.fetchval(f"SELECT count(*) FROM {table}")
    assert in_tx(q) == 0


def test_no_context_catalogs_show_platform_rows_only(orgs):
    async def q(conn):
        return (await conn.fetchval("SELECT count(*) FROM providers WHERE tenant_id IS NOT NULL"),
                await conn.fetchval("SELECT count(*) FROM ai_act_requirements WHERE tenant_id IS NOT NULL"))
    assert in_tx(q) == (0, 0)


@pytest.mark.parametrize("direction", ["A->B", "B->A"])
@pytest.mark.parametrize("table", ["agents", "audit_log", "users", "policies", "api_keys",
                                   "oversight_queue", "refresh_tokens", "app_settings_values",
                                   "providers", "ai_act_requirements"])
def test_tenant_context_sees_only_own_rows(orgs, direction, table):
    actor, other = orgs if direction == "A->B" else orgs[::-1]

    async def q(conn):
        return [str(r["tenant_id"]) if r["tenant_id"] else None
                for r in await conn.fetch(f"SELECT DISTINCT tenant_id FROM {table}")]
    tenants = set(in_tx(q, tenant_id=actor.id))
    assert other.id not in tenants
    assert tenants <= {actor.id, None}
    if table in ("providers", "ai_act_requirements", "agents", "users", "policies", "api_keys",
                 "oversight_queue", "audit_log", "app_settings_values"):
        assert actor.id in tenants, f"{table}: brak własnych wierszy {actor.label} w kontekście"


def test_tenants_table_shows_only_self(orgs):
    a, b = orgs

    async def q(conn):
        return [str(r["id"]) for r in await conn.fetch("SELECT id FROM tenants")]
    assert in_tx(q, tenant_id=a.id) == [a.id]


def test_select_foreign_row_by_id_returns_nothing(orgs):
    a, b = orgs

    async def q(conn):
        return [
            await conn.fetchval("SELECT count(*) FROM agents WHERE id = $1", uuid.UUID(b.agent_id)),
            await conn.fetchval("SELECT count(*) FROM users WHERE id = $1", uuid.UUID(b.partner_id)),
            await conn.fetchval("SELECT count(*) FROM api_keys WHERE id = $1", uuid.UUID(b.api_key_id)),
            await conn.fetchval("SELECT count(*) FROM providers WHERE id = $1", uuid.UUID(b.provider_id)),
            await conn.fetchval("SELECT count(*) FROM audit_log WHERE call_id = $1", uuid.UUID(b.audit_call_id)),
        ]
    assert in_tx(q, tenant_id=a.id) == [0, 0, 0, 0, 0]


INSERT_FOREIGN = {
    "agents": ("INSERT INTO agents (tenant_id, name, owner_name, owner_email) VALUES ($1, 'x', 'x', 'x')", ()),
    "users": ("INSERT INTO users (tenant_id, email, full_name, role) VALUES ($1, 'rls@x.test', 'x', 'reviewer')", ()),
    "policies": ("INSERT INTO policies (tenant_id, name, level, rule_type) VALUES ($1, 'x', 'org', 'deny')", ()),
    "providers": ("INSERT INTO providers (tenant_id, name, provider_type) VALUES ($1, 'x', 'custom')", ()),
    "ai_act_requirements": ("INSERT INTO ai_act_requirements (tenant_id, risk_level, article_ref, "
                            "requirement_title, requirement_text) VALUES ($1, 'minimal', 'x', 'x', 'x')", ()),
    "audit_log": ("INSERT INTO audit_log (tenant_id, agent_id, event_type, policy_result) "
                  "VALUES ($1, gen_random_uuid(), 'x', 'allowed')", ()),
    "app_settings_values": ("INSERT INTO app_settings_values (tenant_id, key, value) "
                            "VALUES ($1, 'pagination.audit_default_limit', '5')", ()),
}


@pytest.mark.parametrize("table", list(INSERT_FOREIGN))
def test_insert_with_foreign_tenant_id_rejected(orgs, table):
    a, b = orgs
    sql, _ = INSERT_FOREIGN[table]

    async def q(conn):
        await conn.execute(sql, uuid.UUID(b.id))
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError, match="row-level security"):
        in_tx(q, tenant_id=a.id)


def test_insert_without_tenant_id_gets_context_tenant(orgs):
    a, _ = orgs

    async def q(conn):
        return await conn.fetchval(
            "INSERT INTO agents (name, owner_name, owner_email) VALUES ('x', 'x', 'x') RETURNING tenant_id")
    assert str(in_tx(q, tenant_id=a.id)) == a.id


def test_insert_platform_catalog_row_rejected(orgs):
    """tenant_id NULL (wiersz platformy) nie do zapisania w kontekście organizacji."""
    a, _ = orgs

    async def q(conn):
        await conn.execute("INSERT INTO providers (tenant_id, name, provider_type) VALUES (NULL, 'x', 'custom')")
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError, match="row-level security"):
        in_tx(q, tenant_id=a.id)


def test_update_own_row_to_foreign_tenant_rejected(orgs):
    a, b = orgs

    async def q(conn):
        await conn.execute("UPDATE agents SET tenant_id = $1 WHERE id = $2", uuid.UUID(b.id), uuid.UUID(a.agent_id))
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError, match="row-level security"):
        in_tx(q, tenant_id=a.id)


def test_update_delete_foreign_rows_affect_nothing(orgs):
    a, b = orgs

    async def q(conn):
        return [
            await conn.execute("UPDATE agents SET name = 'hacked' WHERE id = $1", uuid.UUID(b.agent_id)),
            await conn.execute("DELETE FROM policies WHERE id = $1", uuid.UUID(b.policy_id)),
            await conn.execute("UPDATE users SET full_name = 'hacked' WHERE tenant_id = $1", uuid.UUID(b.id)),
            await conn.execute("DELETE FROM api_keys WHERE id = $1", uuid.UUID(b.api_key_id)),
            await conn.execute("UPDATE providers SET name = 'hacked' WHERE id = $1", uuid.UUID(b.provider_id)),
            await conn.execute("DELETE FROM ai_act_requirements WHERE id = $1", uuid.UUID(b.requirement_id)),
            await conn.execute("UPDATE tenants SET name = 'hacked' WHERE id = $1", uuid.UUID(b.id)),
        ]
    assert in_tx(q, tenant_id=a.id) == ["UPDATE 0", "DELETE 0", "UPDATE 0", "DELETE 0",
                                        "UPDATE 0", "DELETE 0", "UPDATE 0"]


def test_own_tenant_row_not_writable(orgs):
    """Organizacja widzi swój wiersz w tenants, ale zmiana tylko w trybie platformy."""
    a, _ = orgs

    async def q(conn):
        return await conn.execute("UPDATE tenants SET name = name WHERE id = $1", uuid.UUID(a.id))
    try:
        result = in_tx(q, tenant_id=a.id)
    except asyncpg.exceptions.InsufficientPrivilegeError:
        return
    pytest.fail(f"UPDATE własnego wiersza tenants w kontekście organizacji powiódł się: {result}")


def test_platform_catalog_rows_not_modifiable(orgs, platform_ids):
    a, _ = orgs
    if not platform_ids["providers"] or not platform_ids["requirements"]:
        pytest.skip("Brak wierszy platformy")
    pid = uuid.UUID(platform_ids["providers"][0])
    rid = uuid.UUID(platform_ids["requirements"][0])

    async def q(conn):
        return [
            await conn.fetchval("SELECT count(*) FROM providers WHERE id = $1", pid),  # widoczny
            await conn.execute("UPDATE providers SET notes = 'hacked' WHERE id = $1", pid),
            await conn.execute("DELETE FROM providers WHERE id = $1", pid),
            await conn.execute("UPDATE ai_act_requirements SET requirement_title = 'hacked' WHERE id = $1", rid),
            await conn.execute("DELETE FROM ai_act_requirements WHERE id = $1", rid),
        ]
    assert in_tx(q, tenant_id=a.id) == [1, "UPDATE 0", "DELETE 0", "UPDATE 0", "DELETE 0"]


@pytest.mark.parametrize("table", ["policies", "api_keys", "oversight_queue"])
def test_composite_fk_blocks_foreign_agent(orgs, table):
    """Złożony FK (tenant_id, agent_id): nawet w trybie platformy (bez RLS) nie da się
    powiązać wiersza organizacji A z agentem organizacji B."""
    a, b = orgs
    sql = {
        "policies": "INSERT INTO policies (tenant_id, name, level, rule_type, agent_id) "
                    "VALUES ($1, 'x', 'agent', 'deny', $2)",
        "api_keys": "INSERT INTO api_keys (tenant_id, name, key_hash, key_prefix, agent_id) "
                    "VALUES ($1, 'x', 'x', 'x', $2)",
        "oversight_queue": "INSERT INTO oversight_queue (tenant_id, agent_id, task_id, agent_decision, "
                           "ttl_expires_at) VALUES ($1, $2, 'x', 'x', NOW())",
    }[table]

    async def q(conn):
        await conn.execute(sql, uuid.UUID(a.id), uuid.UUID(b.agent_id))
    for kwargs in ({"tenant_id": a.id}, {"platform": True}):
        with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
            in_tx(q, **kwargs)


def test_audit_log_update_delete_blocked_by_trigger(orgs):
    a, _ = orgs
    call = uuid.UUID(a.audit_call_id)

    async def upd(conn):
        await conn.execute("UPDATE audit_log SET block_reason = 'x' WHERE call_id = $1", call)

    async def dele(conn):
        await conn.execute("DELETE FROM audit_log WHERE call_id = $1", call)

    async def purge_non_demo(conn):
        # app.audit_purge działa tylko dla organizacji demo (albo w trybie platformy)
        await conn.execute("SELECT set_config('app.audit_purge', 'on', true)")
        await conn.execute("DELETE FROM audit_log WHERE call_id = $1", call)

    for fn in (upd, dele, purge_non_demo):
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError, match="niezmienny"):
            in_tx(fn, tenant_id=a.id)
    # Tryb platformy bez app.audit_purge — także zabronione
    for fn in (upd, dele):
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError, match="niezmienny"):
            in_tx(fn, platform=True)


def test_context_setting_is_transaction_local(orgs):
    """set_config(..., true) nie może „przeciekać” poza transakcję na tym samym połączeniu."""
    a, _ = orgs

    async def runner():
        conn = await asyncpg.connect(app_dsn())
        try:
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", a.id)
                inside = await conn.fetchval("SELECT count(*) FROM agents")
            outside = await conn.fetchval("SELECT count(*) FROM agents")
            return inside, outside
        finally:
            await conn.close()
    inside, outside = asyncio.run(runner())
    assert inside >= 1 and outside == 0


@pytest.mark.parametrize("sql", [
    "CREATE TABLE rls_probe (id int)",
    "TRUNCATE agents",
    "TRUNCATE audit_log",
    "ALTER TABLE agents DISABLE ROW LEVEL SECURITY",
    "ALTER TABLE agents NO FORCE ROW LEVEL SECURITY",
    "DROP POLICY tenant_isolation ON agents",
    "SET row_security = off; SELECT count(*) FROM agents",
    "SELECT * FROM schema_migrations",
])
def test_app_role_has_no_ddl_or_bypass(orgs, sql):
    async def q(conn):
        return await conn.execute(sql)
    with pytest.raises(asyncpg.exceptions.PostgresError):
        in_tx(q, tenant_id=orgs[0].id)


def test_set_row_security_off_does_not_bypass(orgs):
    """row_security=off dla roli bez BYPASSRLS → błąd, nie cichy odczyt wszystkiego."""
    async def q(conn):
        await conn.execute("SET LOCAL row_security = off")
        return await conn.fetchval("SELECT count(*) FROM agents")
    try:
        count = in_tx(q)
    except asyncpg.exceptions.PostgresError:
        return
    assert count == 0, f"row_security=off ujawnił {count} wierszy agents"
