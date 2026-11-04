import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from dependencies.auth import CurrentUser, get_current_user, require_role
from i18n import t
from repositories import audit_repository as audit_repo
from services import settings_service
from services.block_reasons import localize_block_reason

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/audit", tags=["audit"])

_AUDIT_ROLES = require_role("partner", "it_admin", "compliance_officer", "associate")


@router.get("")
async def list_audit(
    agent_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    policy_result: Optional[str] = Query(None),
    has_pii: Optional[bool] = Query(None),
    days: Optional[int] = Query(None, ge=1),
    limit: Optional[int] = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(_AUDIT_ROLES),
):
    """Dziennik audytowy z filtrowaniem."""
    days = days or settings_service.get_int("pagination.default_window_days", 7)
    max_limit = settings_service.get_int("pagination.audit_max_limit", 500)
    limit = min(limit or settings_service.get_int("pagination.audit_default_limit", 100), max_limit)
    rows = await audit_repo.list_audit(
        days=days,
        limit=limit,
        offset=offset,
        agent_id=agent_id,
        event_type=event_type,
        policy_result=policy_result,
        has_pii=has_pii,
    )
    return [_row_to_dict(r, keep_metadata=False) for r in rows]


@router.get("/summary")
async def get_summary(
    days: Optional[int] = Query(None, ge=1),
    user: CurrentUser = Depends(_AUDIT_ROLES),
):
    """Podsumowanie dziennika audytowego."""
    days = days or settings_service.get_int("pagination.default_window_days", 7)
    row = await audit_repo.summary(days)
    return {**dict(row), "period_days": days}


@router.get("/{call_id}")
async def get_call(call_id: str, user: CurrentUser = Depends(_AUDIT_ROLES)):
    """Szczegóły pojedynczego wywołania."""
    row = await audit_repo.get_call(call_id)
    if not row:
        raise HTTPException(404, t("audit.errors.call_not_found", call_id=call_id))
    return _row_to_dict(row)


def _row_to_dict(row, keep_metadata: bool = True) -> dict:
    d = dict(row)
    # Powód blokady w języku żądania (kod + parametry z metadata, fallback: tekst z bazy)
    metadata = d.get("metadata") if isinstance(d.get("metadata"), dict) else None
    if "block_reason" in d:
        d["block_reason"] = localize_block_reason(d["block_reason"], metadata)
    if not keep_metadata:
        d.pop("metadata", None)
    for k, v in d.items():
        if hasattr(v, 'isoformat'):
            d[k] = v.isoformat()
        elif hasattr(v, '__iter__') and not isinstance(v, (str, bytes, dict)):
            d[k] = list(v)
    for f in ("id", "agent_id", "call_id"):
        if d.get(f):
            d[f] = str(d[f])
    return d
