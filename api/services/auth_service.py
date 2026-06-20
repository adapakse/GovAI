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

logger = logging.getLogger(__name__)

# ── Hasła ─────────────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt(12)).decode()

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False

# ── JWT access token ──────────────────────────────────────────────────────────

def create_access_token(user_id: str, email: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
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
        raise JWTError("Nieprawidłowy typ tokenu")
    return payload

# ── Refresh token ─────────────────────────────────────────────────────────────

def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()

async def create_refresh_token(
    user_id: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> str:
    """Generuje refresh token, zapisuje hash w DB, zwraca surowy token dla klienta."""
    raw = secrets.token_urlsafe(48)
    token_hash = _hash_token(raw)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)

    pool = get_pool()
    await pool.execute(
        """INSERT INTO refresh_tokens (user_id, token_hash, expires_at, ip_address, user_agent)
           VALUES ($1, $2, $3, $4, $5)""",
        user_id, token_hash, expires_at, ip_address, user_agent,
    )
    return raw

async def verify_refresh_token(raw: str) -> Optional[dict]:
    """Weryfikuje token i zwraca {'user_id', 'token_id'} albo None."""
    token_hash = _hash_token(raw)
    pool = get_pool()
    row = await pool.fetchrow(
        """SELECT id, user_id FROM refresh_tokens
           WHERE token_hash = $1 AND NOT revoked AND expires_at > NOW()""",
        token_hash,
    )
    if not row:
        return None
    return {"user_id": str(row["user_id"]), "token_id": str(row["id"])}

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

async def get_user_by_email(email: str) -> Optional[dict]:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, email, full_name, role, status, password_hash FROM users WHERE email = $1",
        email.lower().strip(),
    )
    return dict(row) if row else None

async def get_user_by_id(user_id: str) -> Optional[dict]:
    pool = get_pool()
    row = await pool.fetchrow(
        """SELECT id, email, full_name, role, status, department, phone,
                  last_login_at, created_at, updated_at
           FROM users WHERE id = $1""",
        user_id,
    )
    return dict(row) if row else None

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
