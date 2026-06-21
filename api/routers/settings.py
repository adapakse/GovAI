"""
Router parametrów aplikacji (panel "Parametry").

  GET  /settings            — wszystkie parametry pogrupowane wg kategorii (odczyt: zalogowany)
  GET  /settings/{key}      — pojedynczy parametr
  PUT  /settings/{key}      — zmiana wartości (tylko it_admin)
  POST /settings/reload     — wymuszenie przeładowania cache (tylko it_admin)
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dependencies.auth import CurrentUser, get_current_user, require_role
from repositories import settings_repository as repo
from services import settings_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["settings"])

_ADMIN = require_role("it_admin")


class SettingUpdate(BaseModel):
    value: Any


def _row_to_dict(row: dict) -> dict:
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, Decimal):
            d[k] = float(v)
        elif hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


@router.get("")
async def list_settings(user: CurrentUser = Depends(get_current_user)):
    """Parametry pogrupowane wg kategorii — do renderowania panelu."""
    rows = await repo.fetch_all()
    grouped: dict[str, list] = {}
    for r in rows:
        grouped.setdefault(r["category"], []).append(_row_to_dict(r))
    return grouped


@router.get("/{key}")
async def get_setting(key: str, user: CurrentUser = Depends(get_current_user)):
    row = await repo.fetch_one(key)
    if not row:
        raise HTTPException(404, f"Parametr '{key}' nie istnieje")
    return _row_to_dict(row)


@router.put("/{key}")
async def update_setting(
    key: str,
    body: SettingUpdate,
    user: CurrentUser = Depends(_ADMIN),
):
    """Zmiana wartości parametru. Waliduje typ i zakres min/max."""
    meta = await repo.fetch_one(key)
    if not meta:
        raise HTTPException(404, f"Parametr '{key}' nie istnieje")
    if not meta.get("editable", True):
        raise HTTPException(403, f"Parametr '{key}' nie jest edytowalny")

    try:
        row = await settings_service.set_value(key, body.value, meta, user.email)
    except ValueError as exc:
        raise HTTPException(400, f"Nieprawidłowa wartość: {exc}")

    logger.info("Parametr '%s' zmieniony na %r przez %s", key, body.value, user.email)
    return _row_to_dict(row)


@router.post("/reload")
async def reload_settings(user: CurrentUser = Depends(_ADMIN)):
    """Ręczne przeładowanie cache z bazy."""
    await settings_service.load()
    return {"status": "reloaded"}
