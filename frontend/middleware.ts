import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { LOCALE_COOKIE, isLocale } from '@/i18n/locales';

const PUBLIC_PATHS = ['/login'];

// Za reverse proxy (Azure Container Apps: govai-edge podmienia Host na nazwę
// aplikacji wewnętrznej) request.url wskazuje adres wewnętrzny — adres
// przekierowania budujemy z X-Forwarded-Host / X-Forwarded-Proto (ustawia je
// edge lub Caddy), a bez nich jak dotąd z request.url.
function publicUrl(request: NextRequest, pathname: string): URL {
  const url = new URL(request.url);
  url.pathname = pathname;
  const forwardedHost = request.headers.get('x-forwarded-host')?.split(',')[0].trim();
  if (forwardedHost) {
    url.host = forwardedHost;   // host[:port]; bez portu — port domyślny protokołu
    if (!forwardedHost.includes(':')) url.port = '';
    const forwardedProto = request.headers.get('x-forwarded-proto')?.split(',')[0].trim();
    if (forwardedProto === 'https' || forwardedProto === 'http') url.protocol = forwardedProto + ':';
  }
  return url;
}

export function middleware(request: NextRequest) {
  const { pathname, searchParams } = request.nextUrl;

  // ?lang=xx (np. link "Zaloguj" z landing page) — zapamiętaj jako jawny wybór
  // języka i przekieruj na ten sam adres bez parametru.
  const lang = searchParams.get('lang');
  if (lang !== null) {
    const clean = publicUrl(request, pathname);
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
    const loginUrl = publicUrl(request, '/login');
    loginUrl.search = '';
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico|.*\\.png$).*)'],
};
