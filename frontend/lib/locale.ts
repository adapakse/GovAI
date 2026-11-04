// Klientowa obsługa języka: ciasteczko govai_locale + zapis w profilu.
//
// Kolejność ustalania języka (jak w CRMtree):
//   1. users.locale (wybór zapisany w profilu, null = "domyślny instancji")
//   2. ciasteczko z jawnego wyboru przed zalogowaniem (przełącznik na ekranie
//      logowania albo ?lang= z landing page — patrz middleware.ts)
//   3. domyślny język instancji (app_settings i18n.default_locale)
// Przed zalogowaniem: ciasteczko → Accept-Language przeglądarki → 'pl'
// (rozstrzyga serwer w i18n/request.ts).
//
// Zmiana języka przeładowuje stronę — komunikaty ładuje serwer Next przy renderze.
import { DEFAULT_LOCALE, INTL_LOCALE, LOCALE_COOKIE, isLocale, type Locale } from '@/i18n/locales';

const ONE_YEAR = 60 * 60 * 24 * 365;

export function getLocaleCookie(): Locale | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${LOCALE_COOKIE}=([^;]*)`));
  const value = match ? decodeURIComponent(match[1]) : null;
  return isLocale(value) ? value : null;
}

export function setLocaleCookie(locale: Locale): void {
  document.cookie = `${LOCALE_COOKIE}=${locale}; path=/; max-age=${ONE_YEAR}; SameSite=Lax`;
}

// Język bieżącego renderu (<html lang>) — ustawiany przez layout z i18n/request.ts.
export function getActiveLocale(): Locale {
  if (typeof document === 'undefined') return DEFAULT_LOCALE;
  const lang = document.documentElement.lang;
  return isLocale(lang) ? lang : DEFAULT_LOCALE;
}

export function intlLocale(locale: Locale = getActiveLocale()): string {
  return INTL_LOCALE[locale];
}

export interface LocalePreference {
  locale: string | null;          // users.locale — null = "domyślny instancji"
  default_locale: string;         // app_settings i18n.default_locale
}

export function effectiveLocale(pref: LocalePreference): Locale {
  if (isLocale(pref.locale)) return pref.locale;
  if (isLocale(pref.default_locale)) return pref.default_locale;
  return DEFAULT_LOCALE;
}
