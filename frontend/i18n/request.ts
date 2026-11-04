import { cookies, headers } from 'next/headers';
import type { AbstractIntlMessages } from 'next-intl';
import { getRequestConfig } from 'next-intl/server';
import { DEFAULT_LOCALE, LOCALE_COOKIE, NAMESPACES, isLocale, matchLocale, type Locale } from './locales';

type Messages = AbstractIntlMessages;

// Bez prefiksu językowego w URL: język z ciasteczka (prawdziwy wybór
// użytkownika lub język z profilu po zalogowaniu), potem Accept-Language
// przeglądarki, potem polski.
function resolveLocale(): Locale {
  const fromCookie = cookies().get(LOCALE_COOKIE)?.value;
  if (isLocale(fromCookie)) return fromCookie;
  return matchLocale(headers().get('accept-language')) ?? DEFAULT_LOCALE;
}

async function loadNamespace(locale: Locale, ns: string): Promise<Messages> {
  try {
    return (await import(`../messages/${locale}/${ns}.json`)).default as Messages;
  } catch {
    return {};
  }
}

function deepMerge(base: Messages, override: Messages): Messages {
  const out: Messages = { ...base };
  for (const [key, value] of Object.entries(override)) {
    const prev = out[key];
    out[key] =
      prev && typeof prev === 'object' && value && typeof value === 'object'
        ? deepMerge(prev, value)
        : value;
  }
  return out;
}

async function loadMessages(locale: Locale): Promise<Messages> {
  const messages: Messages = {};
  await Promise.all(
    NAMESPACES.map(async (ns) => {
      const source = await loadNamespace(DEFAULT_LOCALE, ns);
      // Brakujące klucze w danym języku spadają na polski (język źródłowy).
      messages[ns] = locale === DEFAULT_LOCALE ? source : deepMerge(source, await loadNamespace(locale, ns));
    }),
  );
  return messages;
}

export default getRequestConfig(async () => {
  const locale = resolveLocale();
  return {
    locale,
    messages: await loadMessages(locale),
    timeZone: 'Europe/Warsaw',
  };
});
