"""
Router /providers — zarządzanie dostawcami modeli LLM.
Dostęp: partner, it_admin.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dependencies.auth import CurrentUser, get_current_user, require_role
from repositories import providers_repository as providers_repo

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
    rows = await providers_repo.list_providers(active_only=active_only)
    return [_row_to_dict(r) for r in rows]


@router.get("/{provider_id}")
async def get_provider(
    provider_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    row = await providers_repo.get_provider(provider_id)
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

    row = await providers_repo.insert_provider(
        name=body.name,
        provider_type=body.provider_type,
        model_ids=body.model_ids,
        base_url=body.base_url,
        api_key_env=body.api_key_env,
        max_data_sensitivity=body.max_data_sensitivity,
        priority=body.priority,
        notes=body.notes,
        created_by=user.id,
    )
    logger.info("Provider '%s' utworzony przez %s", body.name, user.email)
    return _row_to_dict(row)


@router.patch("/{provider_id}")
async def update_provider(
    provider_id: str,
    body: ProviderUpdate,
    user: CurrentUser = Depends(_WRITE_ROLES),
):
    existing = await providers_repo.get_provider_id(provider_id)
    if not existing:
        raise HTTPException(404, "Provider nie znaleziony")

    if body.max_data_sensitivity and body.max_data_sensitivity not in VALID_SENSITIVITY:
        raise HTTPException(400, f"Nieprawidłowy max_data_sensitivity. Dozwolone: {sorted(VALID_SENSITIVITY)}")

    row = await providers_repo.update_provider(
        provider_id,
        name=body.name,
        base_url=body.base_url,
        api_key_env=body.api_key_env,
        priority=body.priority,
        active=body.active,
        is_healthy=body.is_healthy,
        notes=body.notes,
        model_ids=body.model_ids,
        max_data_sensitivity=body.max_data_sensitivity,
    )
    if row is None:
        return await get_provider(provider_id, user)

    logger.info("Provider '%s' zaktualizowany przez %s", provider_id, user.email)
    return _row_to_dict(row)


@router.delete("/{provider_id}")
async def delete_provider(
    provider_id: str,
    user: CurrentUser = Depends(_WRITE_ROLES),
):
    row = await providers_repo.delete_provider(provider_id)
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
    row = await providers_repo.set_health(provider_id, healthy)
    if not row:
        raise HTTPException(404, "Provider nie znaleziony")
    return _row_to_dict(row)
