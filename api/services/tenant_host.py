"""
Organizacja z adresu: {slug}.<domena bazowa> (TENANT_BASE_DOMAINS, np. govai.pl).

Adres służy tylko do wyboru organizacji przy logowaniu i jako blokada
(sesja organizacji A na subdomenie B → 403). Dane organizacji zawsze wynikają
z rekordu użytkownika — nagłówek Host można podrobić.
"""
from __future__ import annotations

import re
from typing import Optional

from config import settings

# Subdomeny techniczne — nigdy nie są organizacją (app = logowanie uniwersalne).
RESERVED_SLUGS = frozenset({
    "app", "api", "www", "admin", "int", "staging", "stage", "dev", "test", "preview",
    "mail", "smtp", "imap", "ftp", "static", "cdn", "assets", "status", "docs", "gateway",
})

_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


def is_valid_slug(slug: str) -> bool:
    return bool(_SLUG_RE.match(slug)) and len(slug) <= 63 and slug not in RESERVED_SLUGS


def slug_from_host(host: Optional[str]) -> Optional[str]:
    """Slug organizacji z nagłówka Host albo None (adres uniwersalny, inna domena)."""
    if not host:
        return None
    hostname = host.split(":")[0].strip().lower().rstrip(".")
    for base in settings.tenant_base_domains:
        suffix = "." + base
        if hostname.endswith(suffix):
            label = hostname[: -len(suffix)]
            if "." not in label and _SLUG_RE.match(label) and label not in RESERVED_SLUGS:
                return label
    return None
