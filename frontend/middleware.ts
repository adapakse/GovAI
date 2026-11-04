import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { LOCALE_COOKIE, isLocale } from '@/i18n/locales';

const PUBLIC_PATHS = ['/login'];

export function middleware(request: NextRequest) {
  const { pathname, searchParams } = request.nextUrl;

  // ?lang=xx (np. link "Zaloguj" z landing page) — zapamiętaj jako jawny wybór
  // języka i przekieruj na ten sam adres bez parametru.
  const lang = searchParams.get('lang');
  if (lang !== null) {
    const clean = request.nextUrl.clone();
    clean.searchParams.delete('lang');
    const response = NextResponse.redirect(clean);
    if (isLocale(lang)) {
      response.cookies.set(LOCALE_COOKIE, lang, { path: '/', maxAge: 60 * 60 * 24 * 365, sameSite: 'lax' });
    }
    return response;
  }

  if (PUBLIC_PATHS.some(p => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  const session = request.cookies.get('gai_session');
  if (!session?.value) {
    const loginUrl = new URL('/login', request.url);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico|.*\\.png$).*)'],
};
