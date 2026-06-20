"""
Router /providers — zarządzanie dostawcami modeli LLM.
Dostęp: partner, it_admin.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database import get_pool
from dependencies.auth import CurrentUser, get_current_user, require_role

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/providers", tags=["providers"])

_WRITE_ROLES = require_role("partner", "it_admin")

# ── Schematy ───────────────────────────────────────────────────────────────────

VALID_SENSITIVITY = {"public", "internal", "confidential", "privileged"}
VALID_TYPES = {"openai", "anthropic", "deepseek", "google", "bielik", "ollama", "vllm", "custom"}


class ProviderCreate(BaseModel):
    name: str
    provider_type: str
    model_ids: list[str] = []
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    max_data_sensitivity: str = "internal"
    priority: int = 100
    notes: Optional[str] = None


class ProviderUpdate(BaseModel):
    name: Optional[str] = None
    model_ids: Optional[list[str]] = None
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    max_data_sensitivity: Optional[str] = None
    priority: Optional[int] = None
    active: Optional[bool] = None
    is_healthy: Optional[bool] = None
    notes: Optional[str] = None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    d = dict(row)
    d["id"] = str(d["id"])
    if d.get("created_by"):
        d["created_by"] = str(d["created_by"])
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    if "model_ids" in d and d["model_ids"] is not None:
        d["model_ids"] = list(d["model_ids"])
    return d


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/")
async def list_providers(
    active_only: bool = False,
    user: CurrentUser = Depends(get_current_user),
):
    pool = get_pool()
    where = "WHERE active = true" if active_only else ""
    rows = await pool.fetch(
        f"""SELECT id, name, provider_type, model_ids, base_url, api_key_env,
                   max_data_sensitivity, active, priority, is_healthy,
                   last_health_check_at, notes, created_by, created_at, updated_at
            FROM providers
            {where}
            ORDER BY priority ASC, name ASC"""
    )
    return [_row_to_dict(r) for r in rows]


@router.get("/{provider_id}")
async def get_provider(
    provider_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    pool = get_pool()
    row = await pool.fetchrow(
        """SELECT id, name, provider_type, model_ids, base_url, api_key_env,
                  max_data_sensitivity, active, priority, is_healthy,
                  last_health_check_at, notes, created_by, created_at, updated_at
           FROM providers WHERE id = $1""",
        provider_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Provider nie znaleziony")
    return _row_to_dict(row)


@router.post("/", status_code=201)
async def create_provider(
    body: ProviderCreate,
    user: CurrentUser = Depends(_WRITE_ROLES),
):
    if body.provider_type not in VALID_TYPES:
        raise HTTPException(400, f"Nieznany provider_type. Dozwolone: {sorted(VALID_TYPES)}")
    if body.max_data_sensitivity not in VALID_SENSITIVITY:
        raise HTTPException(400, f"Nieprawidłowy max_data_sensitivity. Dozwolone: {sorted(VALID_SENSITIVITY)}")

    pool = get_pool()
    row = await pool.fetchrow(
        """INSERT INTO providers
               (name, provider_type, model_ids, base_url, api_key_env,
                max_data_sensitivity, priority, notes, created_by)
           VALUES ($1, $2, $3, $4, $5, $6::data_sensitivity_level, $7, $8, $9)
           RETURNING id, name, provider_type, model_ids, base_url, api_key_env,
                     max_data_sensitivity, active, priority, is_healthy,
                     last_health_check_at, notes, created_by, created_at, updated_at""",
        body.name,
        body.provider_type,
        body.model_ids,
        body.base_url,
        body.api_key_env,
        body.max_data_sensitivity,
        body.priority,
        body.notes,
        user.id,
    )
    logger.info("Provider '%s' utworzony przez %s", body.name, user.email)
    return _row_to_dict(row)


@router.patch("/{provider_id}")
async def update_provider(
    provider_id: str,
    body: ProviderUpdate,
    user: CurrentUser = Depends(_WRITE_ROLES),
):
    pool = get_pool()
    existing = await pool.fetchrow("SELECT id FROM providers WHERE id = $1", provider_id)
    if not existing:
        raise HTTPException(404, "Provider nie znaleziony")

    if body.max_data_sensitivity and body.max_data_sensitivity not in VALID_SENSITIVITY:
        raise HTTPException(400, f"Nieprawidłowy max_data_sensitivity. Dozwolone: {sorted(VALID_SENSITIVITY)}")

    updates, params = [], []
    idx = 1

    simple_fields = [
        ("name", body.name),
        ("base_url", body.base_url),
        ("api_key_env", body.api_key_env),
        ("priority", body.priority),
        ("active", body.active),
        ("is_healthy", body.is_healthy),
        ("notes", body.notes),
    ]
    for field, val in simple_fields:
        if val is not None:
            updates.append(f"{field} = ${idx}")
            params.append(val)
            idx += 1

    if body.model_ids is not None:
        updates.append(f"model_ids = ${idx}")
        params.append(body.model_ids)
        idx += 1

    if body.max_data_sensitivity is not None:
        updates.append(f"max_data_sensitivity = ${idx}::data_sensitivity_level")
        params.append(body.max_data_sensitivity)
        idx += 1

    if not updates:
        return await get_provider(provider_id, user)

    updates.append("updated_at = NOW()")
    params.append(provider_id)

    row = await pool.fetchrow(
        f"""UPDATE providers SET {', '.join(updates)} WHERE id = ${idx}
            RETURNING id, name, provider_type, model_ids, base_url, api_key_env,
                      max_data_sensitivity, active, priority, is_healthy,
                      last_health_check_at, notes, created_by, created_at, updated_at""",
        *params,
    )
    logger.info("Provider '%s' zaktualizowany przez %s", provider_id, user.email)
    return _row_to_dict(row)


@router.delete("/{provider_id}")
async def delete_provider(
    provider_id: str,
    user: CurrentUser = Depends(_WRITE_ROLES),
):
    pool = get_pool()
    row = await pool.fetchrow(
        "DELETE FROM providers WHERE id = $1 RETURNING id, name", provider_id
    )
    if not row:
        raise HTTPException(404, "Provider nie znaleziony")
    logger.info("Provider '%s' usunięty przez %s", row["name"], user.email)
    return {"deleted": str(row["id"]), "name": row["name"]}


@router.patch("/{provider_id}/health")
async def update_health(
    provider_id: str,
    healthy: bool,
    user: CurrentUser = Depends(_WRITE_ROLES),
):
    """Ręczna aktualizacja stanu zdrowia providera (np. po teście połączenia)."""
    pool = get_pool()
    row = await pool.fetchrow(
        """UPDATE providers
           SET is_healthy = $1, last_health_check_at = NOW(), updated_at = NOW()
           WHERE id = $2
           RETURNING id, name, is_healthy, last_health_check_at""",
        healthy, provider_id,
    )
    if not row:
        raise HTTPException(404, "Provider nie znaleziony")
    return _row_to_dict(row)
