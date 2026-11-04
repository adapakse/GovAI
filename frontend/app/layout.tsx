import type { Metadata } from 'next';
import { NextIntlClientProvider } from 'next-intl';
import { getLocale, getMessages, getTranslations } from 'next-intl/server';
import './globals.css';
import Sidebar from '@/components/Sidebar';
import AuthProvider from '@/components/AuthProvider';
import ActingBanner from '@/components/ActingBanner';

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations('shell.meta');
  return {
    title: t('title'),
    description: t('description'),
  };
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = await getLocale();
  const messages = await getMessages();
  return (
    <html lang={locale}>
      <body className="flex h-screen overflow-hidden bg-dark text-white">
        <NextIntlClientProvider locale={locale} messages={messages} timeZone="Europe/Warsaw">
          <AuthProvider>
            <Sidebar />
            <div className="flex-1 flex flex-col min-w-0">
              <ActingBanner />
              <main className="flex-1 overflow-y-auto p-6">
                {children}
              </main>
            </div>
          </AuthProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
