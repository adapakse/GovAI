'use client';

import { createContext, useContext, useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import {
  AuthUser, clearSession, getAccessToken, getUser,
  apiRefresh, getRefreshToken, saveSession,
} from '@/lib/auth';

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
        setUser(stored);
        setIsLoading(false);
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
