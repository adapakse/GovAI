"""
Router /providers — zarządzanie dostawcami modeli LLM.
Dostęp: partner, it_admin.

Multitenancy: lista = providerzy platformy (tenant_id NULL, is_platform=true)
+ własni providerzy organizacji. Wiersze platformy są dla organizacji tylko do
odczytu (403); super-admin zmienia je w trybie platformy (platform_db).
"""
from __future__ import annotations

import logging
from contextlib import nullcontext
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database import platform_db
from dependencies.auth import CurrentUser, get_current_user, require_role
from i18n import t
from repositories import providers_repository as providers_repo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/providers", tags=["providers"])

_WRITE_ROLES = require_role("partner", "it_admin")

# ── Schematy ───────────────────────────────────────────────────────────────────

VALID_SENSITIVITY = {"public", "internal", "confidential", "privileged"}
VALID_TYPES = {"openai", "anthropic", "deepseek", "google", "bielik", "ollama", "vllm", "custom"}

# Zmienne środowiskowe z kluczami platformy, do których provider może się odwołać
# (api_key_env). Bez białej listy dowolna zmienna procesu gatewaya (np. JWT_SECRET,
# DB_PASSWORD) mogła trafić do dostawcy jako klucz. Trzymaj w synchronizacji z
# gateway/models.py (PLATFORM_KEY_ENVS).
PLATFORM_KEY_ENVS = {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "GOOGLE_API_KEY"}


def _validate_key_config(api_key_env: Optional[str], base_url: Optional[str]) -> None:
    """Klucz platformy tylko z białej listy i nigdy razem z własnym base_url —
    inaczej klucz platformy dałoby się wysłać na dowolny serwer."""
    if api_key_env and api_key_env not in PLATFORM_KEY_ENVS:
        raise HTTPException(400, t("providers.errors.key_env_not_allowed", allowed=", ".join(sorted(PLATFORM_KEY_ENVS))))
    if api_key_env and base_url:
        raise HTTPException(400, t("providers.errors.key_env_with_base_url"))


class ProviderCreate(BaseModel):
    name: str
    provider_type: str
    model_ids: list[str] = []
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    max_data_sensitivity: str = "internal"
    priority: int = 100
    notes: Optional[str] = None
    # true = provider platformy (wspólny dla wszystkich organizacji) — tylko super-admin
    is_platform: bool = False


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


def _deny_platform_write(user: CurrentUser) -> None:
    if not user.is_super_admin:
        raise HTTPException(403, t("providers.errors.platform_read_only"))


async def _get_writable(provider_id: str, user: CurrentUser):
    """Provider do zmiany: 404 gdy niewidoczny, 403 gdy to wiersz platformy,
    a użytkownik nie jest super-adminem (RLS i tak odrzuciłby zapis — jako 500)."""
    existing = await providers_repo.get_provider(provider_id)
    if not existing:
        raise HTTPException(404, t("providers.errors.not_found"))
    if existing["is_platform"]:
        _deny_platform_write(user)
    return existing


def _write_scope(is_platform: bool):
    """Wiersze platformy zapisujemy w trybie platformy, własne — w kontekście żądania."""
    return platform_db() if is_platform else nullcontext()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
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
        raise HTTPException(status_code=404, detail=t("providers.errors.not_found"))
    return _row_to_dict(row)


@router.post("", status_code=201)
async def create_provider(
    body: ProviderCreate,
    user: CurrentUser = Depends(_WRITE_ROLES),
):
    if body.provider_type not in VALID_TYPES:
        raise HTTPException(400, t("providers.errors.invalid_type", allowed=sorted(VALID_TYPES)))
    if body.max_data_sensitivity not in VALID_SENSITIVITY:
        raise HTTPException(400, t("providers.errors.invalid_sensitivity", allowed=sorted(VALID_SENSITIVITY)))
    _validate_key_config(body.api_key_env, body.base_url)
    if body.is_platform:
        _deny_platform_write(user)

    # tenant_id z DEFAULT current_tenant_id(): w kontekście organizacji — jej
    # własny wiersz; w trybie platformy — NULL (provider platformy).
    async with _write_scope(body.is_platform):
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
    logger.info("Provider '%s' utworzony przez %s (platforma: %s)", body.name, user.email, body.is_platform)
    return _row_to_dict(row)


@router.patch("/{provider_id}")
async def update_provider(
    provider_id: str,
    body: ProviderUpdate,
    user: CurrentUser = Depends(_WRITE_ROLES),
):
    existing = await _get_writable(provider_id, user)

    if body.max_data_sensitivity and body.max_data_sensitivity not in VALID_SENSITIVITY:
        raise HTTPException(400, t("providers.errors.invalid_sensitivity", allowed=sorted(VALID_SENSITIVITY)))
    # PATCH nie czyści pól (None = bez zmian) — walidujemy stan po zmianie.
    _validate_key_config(
        body.api_key_env if body.api_key_env is not None else existing["api_key_env"],
        body.base_url if body.base_url is not None else existing["base_url"],
    )

    async with _write_scope(existing["is_platform"]):
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
        return _row_to_dict(existing)

    logger.info("Provider '%s' zaktualizowany przez %s", provider_id, user.email)
    return _row_to_dict(row)


@router.delete("/{provider_id}")
async def delete_provider(
    provider_id: str,
    user: CurrentUser = Depends(_WRITE_ROLES),
):
    # Jawna kontrola konieczna: polityka RLS katalogu przy DELETE sprawdza tylko
    # USING (widoczność), a wiersze platformy są widoczne dla organizacji.
    existing = await _get_writable(provider_id, user)
    async with _write_scope(existing["is_platform"]):
        row = await providers_repo.delete_provider(provider_id)
    if not row:
        raise HTTPException(404, t("providers.errors.not_found"))
    logger.info("Provider '%s' usunięty przez %s", row["name"], user.email)
    return {"deleted": str(row["id"]), "name": row["name"]}


@router.patch("/{provider_id}/health")
async def update_health(
    provider_id: str,
    healthy: bool,
    user: CurrentUser = Depends(_WRITE_ROLES),
):
    """Ręczna aktualizacja stanu zdrowia providera (np. po teście połączenia)."""
    existing = await _get_writable(provider_id, user)
    async with _write_scope(existing["is_platform"]):
        row = await providers_repo.set_health(provider_id, healthy)
    if not row:
        raise HTTPException(404, t("providers.errors.not_found"))
    return _row_to_dict(row)
