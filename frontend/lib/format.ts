'use client';

import { useLocale } from 'next-intl';
import type { Locale as DateFnsLocale } from 'date-fns';
import { de, enGB, es, fr, hr, it, pl, ro, ru, sl } from 'date-fns/locale';
import { INTL_LOCALE, type Locale } from '@/i18n/locales';

// Formatowanie dat i liczb w języku aktywnym w UI. Zamiast toLocaleString('pl-PL')
// używaj: const fmt = useFormat(); fmt.dateTime(iso), fmt.number(n) itd.

const DATE_FNS: Record<Locale, DateFnsLocale> = { pl, en: enGB, de, it, es, fr, ro, ru, sl, hr };

export function useIntlLocale(): string {
  return INTL_LOCALE[useLocale() as Locale];
}

export function useDateFnsLocale(): DateFnsLocale {
  return DATE_FNS[useLocale() as Locale];
}

type DateInput = string | number | Date;

export function useFormat() {
  const loc = useIntlLocale();
  const d = (v: DateInput) => (v instanceof Date ? v : new Date(v));
  return {
    locale: loc,
    date: (v: DateInput, opts?: Intl.DateTimeFormatOptions) => d(v).toLocaleDateString(loc, opts),
    time: (v: DateInput, opts?: Intl.DateTimeFormatOptions) => d(v).toLocaleTimeString(loc, opts),
    dateTime: (v: DateInput, opts?: Intl.DateTimeFormatOptions) => d(v).toLocaleString(loc, opts),
    number: (v: number, opts?: Intl.NumberFormatOptions) => v.toLocaleString(loc, opts),
  };
}
