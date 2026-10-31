// Jedno źródło prawdy dla języków frontendu.
// Trzymaj w synchronizacji z: api/i18n/__init__.py (LOCALES),
// gateway/i18n/__init__.py (LOCALES), db/migrations/012_i18n.sql (CHECK users.locale)
// i website/i18n.js (LANGS).

export const LOCALES = ['pl', 'en', 'de', 'it', 'es', 'fr', 'ro', 'ru', 'sl', 'hr'] as const;
export type Locale = (typeof LOCALES)[number];

export const DEFAULT_LOCALE: Locale = 'pl';

// Ciasteczko z aktywnym językiem — czytane przez serwer Next (i18n/request.ts)
// i przez lib/api.ts (nagłówek Accept-Language do API).
export const LOCALE_COOKIE = 'govai_locale';

// Nazwy w danym języku (endonimy) — tak, jak użytkownik szuka swojego języka.
export const LOCALE_NAMES: Record<Locale, string> = {
  pl: 'Polski',
  en: 'English',
  de: 'Deutsch',
  it: 'Italiano',
  es: 'Español',
  fr: 'Français',
  ro: 'Română',
  ru: 'Русский',
  sl: 'Slovenščina',
  hr: 'Hrvatski',
};

// Locale dla Intl/toLocaleString — 'en' jako en-GB (dzień przed miesiącem, zegar 24h).
export const INTL_LOCALE: Record<Locale, string> = {
  pl: 'pl-PL',
  en: 'en-GB',
  de: 'de-DE',
  it: 'it-IT',
  es: 'es-ES',
  fr: 'fr-FR',
  ro: 'ro-RO',
  ru: 'ru-RU',
  sl: 'sl-SI',
  hr: 'hr-HR',
};

// Przestrzenie nazw komunikatów: messages/<locale>/<namespace>.json.
// Nowy plik namespace trzeba dopisać tutaj (ładowanie w i18n/request.ts).
export const NAMESPACES = [
  'common',
  'shell',
  'auth',
  'dashboard',
  'agents',
  'policies',
  'providers',
  'reports',
  'settings',
  'audit',
  'oversight',
  'demo',
] as const;

export function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && (LOCALES as readonly string[]).includes(value);
}

// Dopasowanie nagłówka Accept-Language / navigator.language do obsługiwanego języka.
export function matchLocale(header: string | null | undefined): Locale | null {
  if (!header) return null;
  for (const part of header.split(',')) {
    const code = part.split(';')[0].trim().slice(0, 2).toLowerCase();
    if (isLocale(code)) return code;
  }
  return null;
}
