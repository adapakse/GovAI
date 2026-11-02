'use client';

import { createContext, useContext, useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import {
  AuthUser, clearSession, getAccessToken, getUser,
  apiRefresh, apiMe, getRefreshToken, saveSession,
} from '@/lib/auth';
import { effectiveLocale, getActiveLocale, setLocaleCookie } from '@/lib/locale';

interface AuthCtx {
  user: AuthUser | null;
  isLoading: boolean;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthCtx>({ user: null, isLoading: true, logout: async () => {} });

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
        if (pathname !== '/login') router.replace('/login');
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
        // Sesja sprzed multitenancy (brak tenant) — dociągnij organizację z /auth/me
        if (stored.tenant === undefined) {
          // Gdy /auth/me zawiedzie — tenant: null (brak organizacji = brak funkcji demo), bez zawieszania UI
          apiMe().then(u => setUser(u ?? { ...stored, tenant: null }));
        }
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
    if (!isLoading && !user && pathname !== '/login') {
      router.replace('/login');
    }
  }, [user, isLoading, pathname]);

  const logout = async () => {
    const refresh = getRefreshToken();
    const access = getAccessToken();
    if (refresh && access) {
      const { apiLogout } = await import('@/lib/auth');
      await apiLogout(refresh, access);
    }
    clearSession();
    setUser(null);
    router.replace('/login');
  };

  return (
    <Ctx.Provider value={{ user, isLoading, logout }}>
      {children}
    </Ctx.Provider>
  );
}
