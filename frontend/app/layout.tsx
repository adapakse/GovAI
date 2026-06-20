import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import Sidebar from '@/components/Sidebar';
import AuthProvider from '@/components/AuthProvider';

const inter = Inter({
  subsets: ['latin'],
  weight: ['400', '600', '700', '800'],
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'GovAI — Platforma Zarządzania Agentami AI',
  description: 'Zgodność z EU AI Act | Bramka Bezpieczeństwa | Nadzór Człowieka',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pl" className={inter.className}>
      <body className="flex h-screen overflow-hidden bg-dark text-white">
        <AuthProvider>
          <Sidebar />
          <main className="flex-1 overflow-y-auto p-6">
            {children}
          </main>
        </AuthProvider>
      </body>
    </html>
  );
}
