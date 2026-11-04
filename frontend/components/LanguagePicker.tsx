'use client';

import { useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { LOCALES, LOCALE_NAMES, isLocale, type Locale } from '@/i18n/locales';
import { apiSetLocale, getAccessToken } from '@/lib/auth';
import { effectiveLocale, setLocaleCookie } from '@/lib/locale';
import { useAuth } from '@/components/AuthProvider';

// Przełącznik języka — natywny <select> z nazwami języków (bez flag), jak w CRMtree.
//   mode="compact" — ekran logowania: zapis tylko w ciasteczku (jawny wybór
//                    przed zalogowaniem, przejmowany przy logowaniu).
//   mode="user"    — stopka paska bocznego: zapis w profilu (users.locale);
//                    opcja "domyślny instancji" zapisuje null.
// Każda zmiana przeładowuje stronę — komunikaty renderuje serwer Next.
const DEFAULT_OPTION = '__default__';

export default function LanguagePicker({ mode }: { mode: 'compact' | 'user' }) {
  const t = useTranslations('common.language');
  const active = useLocale() as Locale;
  const { user } = useAuth();
  const [busy, setBusy] = useState(false);

  const current = mode === 'user' && user && !isLocale(user.locale) ? DEFAULT_OPTION : active;

  async function onChange(value: string) {
    setBusy(true);
    try {
      if (mode === 'user' && getAccessToken()) {
        const saved = await apiSetLocale(value === DEFAULT_OPTION ? null : (value as Locale));
        setLocaleCookie(effectiveLocale(saved));
      } else if (isLocale(value)) {
        setLocaleCookie(value);
      }
      window.location.reload();
    } catch {
      setBusy(false);
    }
  }

  const compact = mode === 'compact';
  return (
    <label className={compact ? 'inline-flex items-center gap-2' : 'block'}>
      <span className={compact ? 'sr-only' : 'block text-[10px] uppercase tracking-wider text-mgray/40 mb-1'}>
        {t('label')}
      </span>
      <select
        value={current}
        disabled={busy}
        onChange={e => onChange(e.target.value)}
        className={`rounded-md border border-blue/40 bg-dark text-mgray text-xs px-2 py-1
                    focus:outline-none focus:border-teal disabled:opacity-50 ${compact ? '' : 'w-full'}`}
      >
        {mode === 'user' && user && (
          <option value={DEFAULT_OPTION}>
            {t('instanceDefault', { language: LOCALE_NAMES[effectiveLocale({ locale: null, default_locale: user.default_locale })] })}
          </option>
        )}
        {LOCALES.map(code => (
          <option key={code} value={code}>{LOCALE_NAMES[code]}</option>
        ))}
      </select>
    </label>
  );
}
