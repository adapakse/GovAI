"""
Serwis autentykacji — hasła, JWT, tokeny odświeżania, zarządzanie użytkownikami.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt as _bcrypt
from jose import JWTError, jwt

from config import settings
from database import get_pool
from i18n import t
from services import settings_service

logger = logging.getLogger(__name__)

# ── Hasła ─────────────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    rounds = settings_service.get_int("security.bcrypt_rounds", 12)
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt(rounds)).decode()

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False

# ── JWT access token ──────────────────────────────────────────────────────────

def create_access_token(user_id: str, email: str, role: str, tenant_id: str) -> str:
    minutes = settings_service.get_int("security.access_token_expire_minutes", settings.access_token_expire_minutes)
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        # Organizacja — gateway bierze ją z tokenu (wywołania z UI / symulatora);
        # API i tak sprawdza organizację z rekordu użytkownika przy każdym żądaniu.
        "tenant_id": str(tenant_id),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

def decode_access_token(token: str) -> dict:
    """
    Zwraca payload lub rzuca JWTError.
    Wywołujący powinien obsłużyć JWTError → 401.
    """
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != "access":
        raise JWTError(t("auth.errors.invalid_token_type"))
    return payload

# ── Refresh token ─────────────────────────────────────────────────────────────

def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()

async def create_refresh_token(
    user_id: str,
    tenant_id: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> str:
    """Generuje refresh token, zapisuje hash w DB, zwraca surowy token dla klienta."""
    raw = secrets.token_urlsafe(48)
    token_hash = _hash_token(raw)
    days = settings_service.get_int("security.refresh_token_expire_days", settings.refresh_token_expire_days)
    expires_at = datetime.now(timezone.utc) + timedelta(days=days)

    pool = get_pool()
    await pool.execute(
        """INSERT INTO refresh_tokens (user_id, tenant_id, token_hash, expires_at, ip_address, user_agent)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        user_id, tenant_id, token_hash, expires_at, ip_address, user_agent,
    )
    return raw

async def verify_refresh_token(raw: str) -> Optional[dict]:
    """Weryfikuje token i zwraca {'user_id', 'token_id'} albo None."""
    token_hash = _hash_token(raw)
    pool = get_pool()
    row = await pool.fetchrow(
        """SELECT id, user_id, tenant_id FROM refresh_tokens
           WHERE token_hash = $1 AND NOT revoked AND expires_at > NOW()""",
        token_hash,
    )
    if not row:
        return None
    return {"user_id": str(row["user_id"]), "token_id": str(row["id"]), "tenant_id": str(row["tenant_id"])}

async def revoke_refresh_token(raw: str) -> None:
    token_hash = _hash_token(raw)
    pool = get_pool()
    await pool.execute(
        "UPDATE refresh_tokens SET revoked = true WHERE token_hash = $1",
        token_hash,
    )

async def revoke_all_user_tokens(user_id: str) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE refresh_tokens SET revoked = true WHERE user_id = $1",
        user_id,
    )

# ── Użytkownicy ───────────────────────────────────────────────────────────────

# Użytkownik + jego organizacja — wywoływane w platform_db() (przed ustaleniem
# organizacji: logowanie, weryfikacja tokenu). Organizacja zawsze z rekordu
# użytkownika, nigdy z danych od klienta.
_IDENTITY_SELECT = """
    SELECT u.id, u.email, u.full_name, u.role, u.status, u.password_hash, u.locale,
           u.is_super_admin, u.tenant_id,
           t.slug AS tenant_slug, t.name AS tenant_name, t.status AS tenant_status,
           t.is_demo AS tenant_is_demo, t.deleted_at AS tenant_deleted_at
    FROM users u JOIN tenants t ON t.id = u.tenant_id
"""

async def get_identity(user_id: str) -> Optional[dict]:
    row = await get_pool().fetchrow(_IDENTITY_SELECT + " WHERE u.id = $1", user_id)
    return dict(row) if row else None

async def find_login_identities(email: str, tenant_id: Optional[str] = None) -> list[dict]:
    """Konta o danym e-mailu — w podanej organizacji albo we wszystkich
    (logowanie przez adres uniwersalny app.<domena>)."""
    if tenant_id:
        rows = await get_pool().fetch(
            _IDENTITY_SELECT + " WHERE lower(u.email) = $1 AND u.tenant_id = $2 AND t.deleted_at IS NULL",
            email.lower().strip(), tenant_id,
        )
    else:
        rows = await get_pool().fetch(
            _IDENTITY_SELECT + " WHERE lower(u.email) = $1 AND t.deleted_at IS NULL",
            email.lower().strip(),
        )
    return [dict(r) for r in rows]

async def get_user_by_email(email: str) -> Optional[dict]:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, email, full_name, role, status, password_hash, locale FROM users WHERE lower(email) = $1",
        email.lower().strip(),
    )
    return dict(row) if row else None

async def get_user_by_id(user_id: str) -> Optional[dict]:
    pool = get_pool()
    row = await pool.fetchrow(
        """SELECT id, email, full_name, role, status, department, phone, locale,
                  last_login_at, created_at, updated_at
           FROM users WHERE id = $1""",
        user_id,
    )
    return dict(row) if row else None

async def update_user_locale(user_id: str, locale: Optional[str]) -> None:
    """Język interfejsu użytkownika; None = domyślny język instancji."""
    pool = get_pool()
    await pool.execute(
        "UPDATE users SET locale = $2, updated_at = NOW() WHERE id = $1", user_id, locale,
    )

async def update_last_login(user_id: str) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE users SET last_login_at = NOW() WHERE id = $1", user_id,
    )

async def list_users() -> list[dict]:
    pool = get_pool()
    rows = await pool.fetch(
        """SELECT id, email, full_name, role, status, department, phone,
                  last_login_at, created_at
           FROM users ORDER BY full_name""",
    )
    return [_user_row(r) for r in rows]

async def create_user(
    email: str,
    full_name: str,
    role: str,
    password: str,
    department: Optional[str],
    phone: Optional[str],
    created_by: str,
) -> dict:
    pool = get_pool()
    pw_hash = hash_password(password)
    row = await pool.fetchrow(
        """INSERT INTO users (email, full_name, role, password_hash, department, phone, created_by)
           VALUES ($1, $2, $3::user_role, $4, $5, $6, $7)
           RETURNING id, email, full_name, role, status, department, phone, created_at""",
        email.lower().strip(), full_name, role, pw_hash, department, phone, created_by,
    )
    return _user_row(row)

async def update_user(
    user_id: str,
    full_name: Optional[str],
    role: Optional[str],
    status: Optional[str],
    department: Optional[str],
    phone: Optional[str],
) -> Optional[dict]:
    pool = get_pool()
    updates, params = [], []
    idx = 1
    for field, val in [("full_name", full_name), ("role", role),
                       ("status", status), ("department", department), ("phone", phone)]:
        if val is not None:
            cast = f"::user_role" if field == "role" else f"::user_status" if field == "status" else ""
            updates.append(f"{field} = ${idx}{cast}")
            params.append(val); idx += 1
    if not updates:
        return await get_user_by_id(user_id)
    updates.append("updated_at = NOW()")
    params.append(user_id)
    await pool.execute(
        f"UPDATE users SET {', '.join(updates)} WHERE id = ${idx}", *params,
    )
    return await get_user_by_id(user_id)

async def change_password(user_id: str, new_password: str) -> None:
    pool = get_pool()
    pw_hash = hash_password(new_password)
    await pool.execute(
        "UPDATE users SET password_hash = $1, updated_at = NOW() WHERE id = $2",
        pw_hash, user_id,
    )
    await revoke_all_user_tokens(user_id)

# ── API Keys ──────────────────────────────────────────────────────────────────

def _hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()

async def create_api_key(
    name: str,
    created_by: str,
    agent_id: Optional[str] = None,
    expires_days: Optional[int] = None,
) -> dict:
    """Zwraca {'key': surowy_klucz, 'prefix': ...} — klucz wyświetlany TYLKO RAZ."""
    raw = "gai_" + secrets.token_urlsafe(32)
    prefix = raw[:12]
    key_hash = _hash_api_key(raw)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=expires_days)
        if expires_days else None
    )
    pool = get_pool()
    row = await pool.fetchrow(
        """INSERT INTO api_keys (name, key_hash, key_prefix, created_by, agent_id, expires_at)
           VALUES ($1, $2, $3, $4, $5, $6)
           RETURNING id, name, key_prefix, agent_id, expires_at, created_at""",
        name, key_hash, prefix, created_by, agent_id, expires_at,
    )
    return {**dict(row), "key": raw, "id": str(row["id"])}

async def verify_api_key(raw: str) -> Optional[dict]:
    """Zwraca {'agent_id', 'key_id', 'name'} albo None."""
    key_hash = _hash_api_key(raw)
    pool = get_pool()
    row = await pool.fetchrow(
        """SELECT id, name, agent_id FROM api_keys
           WHERE key_hash = $1
             AND active = true
             AND (expires_at IS NULL OR expires_at > NOW())""",
        key_hash,
    )
    if not row:
        return None
    # Zaktualizuj last_used_at asynchronicznie (nie blokuj odpowiedzi)
    await pool.execute(
        "UPDATE api_keys SET last_used_at = NOW() WHERE id = $1", row["id"],
    )
    return {"agent_id": str(row["agent_id"]) if row["agent_id"] else None,
            "key_id": str(row["id"]), "name": row["name"]}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _user_row(row) -> dict:
    d = dict(row)
    d["id"] = str(d["id"])
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    d.pop("password_hash", None)
    return d
