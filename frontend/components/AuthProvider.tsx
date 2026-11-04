'use client';

import { createContext, useContext, useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import {
  AuthUser, clearSession, getAccessToken, getUser,
  apiRefresh, apiMe, getRefreshToken, logoutTokens,
} from '@/lib/auth';
import { effectiveLocale, getActiveLocale, setLocaleCookie } from '@/lib/locale';

interface AuthCtx {
  user: AuthUser | null;
  isLoading: boolean;
  logout: () => Promise<void>;
  // Ponowny odczyt GET /auth/me (np. po zmianie hasła)
  refreshUser: () => Promise<AuthUser | null>;
}

const Ctx = createContext<AuthCtx>({
  user: null, isLoading: true, logout: async () => {}, refreshUser: async () => null,
});

// Strony bez sesji (logowanie) i bez pełnej aplikacji (wymuszona zmiana hasła)
const LOGIN_PATH = '/login';
const CHANGE_PASSWORD_PATH = '/change-password';

export function useAuth() { return useContext(Ctx); }

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    const init = async () => {
      const token = getAccessToken();
      if (!token) {
        setIsLoading(false);
        if (pathname !== LOGIN_PATH) router.replace(LOGIN_PATH);
        return;
      }

      // Try to decode stored user
      const stored = getUser();
      if (stored) {
        // Język z profilu ma pierwszeństwo — jeśli render poszedł w innym
        // (np. stare ciasteczko na nowym urządzeniu), popraw ciasteczko i przeładuj.
        // Sesje sprzed wprowadzenia języków nie mają default_locale — pomijamy.
        if (stored.default_locale !== undefined) {
          const wanted = effectiveLocale(stored);
          if (wanted !== getActiveLocale()) {
            setLocaleCookie(wanted);
            window.location.reload();
            return;
          }
        }
        setUser(stored);
        setIsLoading(false);
        // Odśwież dane z /auth/me (organizacja, must_change_password, acting_as).
        // Gdy /auth/me zawiedzie, a sesja jest sprzed multitenancy (brak tenant) —
        // tenant: null (brak organizacji = brak funkcji demo), bez zawieszania UI.
        apiMe().then(u => {
          if (u) setUser(u);
          else if (stored.tenant === undefined) setUser({ ...stored, tenant: null });
        });
        return;
      }

      // Fallback: try refresh
      const refresh = getRefreshToken();
      if (refresh) {
        try {
          const { access_token } = await apiRefresh(refresh);
          localStorage.setItem('gai_access', access_token);
          const u = getUser();
          setUser(u);
        } catch {
          clearSession();
          router.replace('/login');
        }
      } else {
        clearSession();
        router.replace('/login');
      }
      setIsLoading(false);
    };
    init();
  }, []);

  // Redirect to login if session disappears mid-session
  useEffect(() => {
    if (!isLoading && !user && pathname !== LOGIN_PATH) {
      router.replace(LOGIN_PATH);
    }
  }, [user, isLoading, pathname]);

  // Hasło tymczasowe — do czasu zmiany dostępna jest tylko strona zmiany hasła
  useEffect(() => {
    if (user?.must_change_password && pathname !== CHANGE_PASSWORD_PATH && pathname !== LOGIN_PATH) {
      router.replace(CHANGE_PASSWORD_PATH);
    }
  }, [user, pathname]);

  const refreshUser = async () => {
    const u = await apiMe();
    if (u) setUser(u);
    return u;
  };

  const logout = async () => {
    // Przy działaniu w organizacji wylogowujemy sesję super-admina (token wejścia nie ma refresh)
    const { refresh, access } = logoutTokens();
    if (refresh && access) {
      const { apiLogout } = await import('@/lib/auth');
      await apiLogout(refresh, access);
    }
    clearSession();
    setUser(null);
    router.replace(LOGIN_PATH);
  };

  return (
    <Ctx.Provider value={{ user, isLoading, logout, refreshUser }}>
      {children}
    </Ctx.Provider>
  );
}
