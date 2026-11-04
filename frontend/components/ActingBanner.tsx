'use client';

import { useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { useAuth } from '@/components/AuthProvider';
import { exitTenantSession, isActingAsTenant } from '@/lib/auth';

// Pasek u góry, gdy super-admin działa w kontekście cudzej organizacji
// (token z POST /platform/tenants/{id}/enter). "Wróć" przywraca sesję super-admina.
export default function ActingBanner() {
  const t = useTranslations('shell.acting');
  const { user, logout } = useAuth();
  const [stored, setStored] = useState(false);

  // localStorage tylko po stronie przeglądarki (bez rozjazdu z renderem serwera)
  useEffect(() => { setStored(isActingAsTenant()); }, [user]);

  if (!user || !(stored || user.acting_as)) return null;

  function goBack() {
    if (exitTenantSession()) window.location.href = '/platform/tenants';
    else logout();  // brak zapisanej sesji super-admina — zostaje ponowne logowanie
  }

  return (
    <div className="flex-shrink-0 flex items-center gap-3 px-6 py-2 bg-orange-600 text-white text-sm">
      <span className="font-semibold">⚠</span>
      <span className="flex-1">
        {t.rich('message', {
          tenant: user.tenant?.name ?? user.tenant?.slug ?? '—',
          b: (c) => <strong>{c}</strong>,
        })}
      </span>
      <button
        onClick={goBack}
        className="px-3 py-1 rounded bg-white/15 hover:bg-white/25 border border-white/30 font-semibold transition-colors"
      >
        {t('back')}
      </button>
    </div>
  );
}
