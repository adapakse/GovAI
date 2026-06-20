const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

const T_ACCESS  = 'gai_access';
const T_REFRESH = 'gai_refresh';
const T_USER    = 'gai_user';

export interface AuthUser {
  id: string;
  email: string;
  full_name: string;
  role: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: AuthUser;
}

// ── Storage helpers ───────────────────────────────────────────────────────────

export function getAccessToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(T_ACCESS);
}

export function getRefreshToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(T_REFRESH);
}

export function getUser(): AuthUser | null {
  if (typeof window === 'undefined') return null;
  const raw = localStorage.getItem(T_USER);
  try { return raw ? JSON.parse(raw) : null; } catch { return null; }
}

export function saveSession(data: LoginResponse): void {
  localStorage.setItem(T_ACCESS, data.access_token);
  localStorage.setItem(T_REFRESH, data.refresh_token);
  localStorage.setItem(T_USER, JSON.stringify(data.user));
  document.cookie = `gai_session=1; path=/; max-age=${60 * 60 * 24 * 7}; SameSite=Lax`;
}

export function clearSession(): void {
  localStorage.removeItem(T_ACCESS);
  localStorage.removeItem(T_REFRESH);
  localStorage.removeItem(T_USER);
  document.cookie = 'gai_session=; path=/; max-age=0';
}

// ── API calls ─────────────────────────────────────────────────────────────────

export async function apiLogin(email: string, password: string): Promise<LoginResponse> {
  const r = await fetch(`${API}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err?.detail ?? 'Logowanie nieudane');
  }
  return r.json();
}

export async function apiRefresh(refresh_token: string): Promise<{ access_token: string }> {
  const r = await fetch(`${API}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token }),
  });
  if (!r.ok) throw new Error('Refresh token wygasł');
  return r.json();
}

export async function apiLogout(refresh_token: string, access_token: string): Promise<void> {
  await fetch(`${API}/auth/logout`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${access_token}`,
    },
    body: JSON.stringify({ refresh_token }),
  }).catch(() => {});
}

// ── Token refresh with retry ──────────────────────────────────────────────────

let _refreshPromise: Promise<string> | null = null;

export async function ensureFreshToken(): Promise<string | null> {
  const access = getAccessToken();
  if (!access) return null;

  // Check if token is about to expire (< 2 min) by decoding payload
  try {
    const payload = JSON.parse(atob(access.split('.')[1]));
    const expiresIn = payload.exp * 1000 - Date.now();
    if (expiresIn > 2 * 60 * 1000) return access;
  } catch {
    return access;
  }

  // Token expiring — refresh (deduplicate concurrent calls)
  if (!_refreshPromise) {
    const refreshToken = getRefreshToken();
    if (!refreshToken) return null;
    _refreshPromise = apiRefresh(refreshToken)
      .then(({ access_token }) => {
        localStorage.setItem(T_ACCESS, access_token);
        return access_token;
      })
      .finally(() => { _refreshPromise = null; });
  }
  return _refreshPromise;
}
