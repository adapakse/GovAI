"""
Repozytorium panelu super-admina — organizacje (tenants), ich użytkownicy
i dziennik operacji platformy (platform_audit_log).

Wszystkie funkcje wołane w trybie platformy (database.platform_db) — poza
tenant_by_id/tenant_by_slug, które działają też w trybie platformy przy
uwierzytelnianiu i na publicznym endpoincie /public/tenant.
Wartości zawsze jako parametry pozycyjne ($n).
"""
from __future__ import annotations

from typing import Any, Optional

from database import get_pool

DEMO_TEMPLATE_TENANT_ID = "d0000000-0000-0000-0000-000000000001"   # govai-demo — szablon polityk

_TENANT_COLUMNS = "t.id, t.slug, t.name, t.status, t.is_demo, t.created_at, t.updated_at, t.deleted_at"


async def list_tenants() -> list:
    return await get_pool().fetch(
        f"""SELECT {_TENANT_COLUMNS},
                   (SELECT count(*) FROM users u WHERE u.tenant_id = t.id)  AS users_count,
                   (SELECT count(*) FROM agents a WHERE a.tenant_id = t.id) AS agents_count
            FROM tenants t
            ORDER BY t.deleted_at IS NOT NULL, t.created_at""",
    )


async def tenant_by_id(tenant_id: str):
    return await get_pool().fetchrow(
        f"SELECT {_TENANT_COLUMNS} FROM tenants t WHERE t.id = $1", tenant_id,
    )


async def active_tenant_by_slug(slug: str):
    """Organizacja aktywna i nieusunięta o danym slugu (branding ekranu logowania)."""
    return await get_pool().fetchrow(
        f"""SELECT {_TENANT_COLUMNS} FROM tenants t
            WHERE t.slug = $1 AND t.deleted_at IS NULL AND t.status = 'active'""",
        slug,
    )


async def slug_taken(slug: str) -> bool:
    return bool(await get_pool().fetchval(
        "SELECT 1 FROM tenants WHERE slug = $1 AND deleted_at IS NULL", slug,
    ))


async def insert_tenant(slug: str, name: str):
    return await get_pool().fetchrow(
        f"""INSERT INTO tenants AS t (slug, name) VALUES ($1, $2)
            RETURNING {_TENANT_COLUMNS}""",
        slug, name,
    )


async def update_tenant(tenant_id: str, name: Optional[str], status: Optional[str]):
    return await get_pool().fetchrow(
        f"""UPDATE tenants AS t
            SET name = COALESCE($2, t.name), status = COALESCE($3, t.status), updated_at = NOW()
            WHERE t.id = $1 AND t.deleted_at IS NULL
            RETURNING {_TENANT_COLUMNS}""",
        tenant_id, name, status,
    )


async def soft_delete_tenant(tenant_id: str):
    return await get_pool().fetchrow(
        f"""UPDATE tenants AS t SET deleted_at = NOW(), updated_at = NOW()
            WHERE t.id = $1 AND t.deleted_at IS NULL
            RETURNING {_TENANT_COLUMNS}""",
        tenant_id,
    )


async def set_tenant_setting(tenant_id: str, key: str, value: Any, updated_by: str) -> None:
    """Nadpisanie parametru organizacji (np. i18n.default_locale) przy zakładaniu."""
    await get_pool().execute(
        """INSERT INTO app_settings_values (tenant_id, key, value, updated_by)
           VALUES ($1, $2, $3, $4)
           ON CONFLICT (tenant_id, key)
           DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, updated_at = NOW()""",
        tenant_id, key, value, updated_by,
    )


async def tenant_setting(tenant_id: str, key: str) -> Any:
    """Wartość efektywna parametru organizacji (nadpisanie albo domyślna platformy)."""
    return await get_pool().fetchval(
        """SELECT COALESCE(v.value, s.value) FROM app_settings s
           LEFT JOIN app_settings_values v ON v.key = s.key AND v.tenant_id = $1
           WHERE s.key = $2""",
        tenant_id, key,
    )


async def copy_template_policies(tenant_id: str, created_by: str) -> int:
    """Kopia aktywnych polityk ogólnych (z policy_code, bez agenta) organizacji
    szablonowej govai-demo do nowej organizacji. Zwraca liczbę skopiowanych."""
    result = await get_pool().execute(
        """INSERT INTO policies (tenant_id, name, level, team, rule_type, condition_json,
                                 action_json, priority, active, policy_code, created_by)
           SELECT $1, name, level, team, rule_type, condition_json,
                  action_json, priority, true, policy_code, $3
           FROM policies
           WHERE tenant_id = $2 AND active AND policy_code IS NOT NULL AND agent_id IS NULL""",
        tenant_id, DEMO_TEMPLATE_TENANT_ID, created_by,
    )
    return int(result.split()[-1]) if result else 0


async def list_tenant_users(tenant_id: str) -> list:
    return await get_pool().fetch(
        """SELECT id, email, full_name, role, status, last_login_at
           FROM users WHERE tenant_id = $1 ORDER BY full_name""",
        tenant_id,
    )


async def tenant_user(tenant_id: str, user_id: str):
    return await get_pool().fetchrow(
        "SELECT id, email, full_name, role, status FROM users WHERE tenant_id = $1 AND id = $2",
        tenant_id, user_id,
    )


async def insert_audit(actor_user_id: Optional[str], actor_email: str, action: str,
                       tenant_id: Optional[str], details: dict) -> None:
    await get_pool().execute(
        """INSERT INTO platform_audit_log (actor_user_id, actor_email, action, tenant_id, details)
           VALUES ($1, $2, $3, $4, $5)""",
        actor_user_id, actor_email, action, tenant_id, details,
    )


async def list_audit(limit: int) -> list:
    return await get_pool().fetch(
        """SELECT l.id, l.time, l.actor_user_id, l.actor_email, l.action, l.tenant_id,
                  t.slug AS tenant_slug, t.name AS tenant_name, l.details
           FROM platform_audit_log l
           LEFT JOIN tenants t ON t.id = l.tenant_id
           ORDER BY l.time DESC, l.id DESC
           LIMIT $1""",
        limit,
    )
