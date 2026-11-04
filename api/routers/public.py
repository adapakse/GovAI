"""
Router /public — endpointy bez logowania.

  GET /public/tenant — organizacja z adresu ({slug}.<TENANT_BASE_DOMAINS>):
      {slug, name, default_locale} albo 404 (adres uniwersalny / nieznana /
      zawieszona / usunięta). Do brandingu i języka ekranu logowania.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from database import platform_db
from i18n import DEFAULT_LOCALE, is_locale, t
from repositories import platform_repository as platform_repo
from services.tenant_host import slug_from_host

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/tenant")
async def public_tenant(request: Request):
    slug = slug_from_host(request.headers.get("host"))
    if slug is None:
        raise HTTPException(404, t("platform.errors.tenant_not_found"))
    async with platform_db():
        tenant = await platform_repo.active_tenant_by_slug(slug)
        locale = await platform_repo.tenant_setting(str(tenant["id"]), "i18n.default_locale") if tenant else None
    if not tenant:
        raise HTTPException(404, t("platform.errors.tenant_not_found"))
    return {
        "slug": tenant["slug"],
        "name": tenant["name"],
        "default_locale": locale if is_locale(locale) else DEFAULT_LOCALE,
    }
