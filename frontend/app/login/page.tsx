'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiLogin, saveSession } from '@/lib/auth';

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const data = await apiLogin(email, password);
      saveSession(data);
      router.replace('/dashboard');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Błąd logowania');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 flex items-center justify-center bg-dark">
      <div className="w-full max-w-md p-8 rounded-2xl border border-blue/30 bg-navy shadow-2xl">

        {/* Logo */}
        <div className="mb-8 text-center flex flex-col items-center gap-4">
          <svg width="56" height="56" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" aria-label="GovAI">
            <defs>
              <linearGradient id="loginGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#00B4D8"/>
                <stop offset="100%" stopColor="#1E6FBF"/>
              </linearGradient>
              <mask id="loginMask">
                <rect x="0" y="0" width="100" height="100" fill="white"/>
                <rect x="58" y="10" width="32" height="32" fill="black"/>
              </mask>
            </defs>
            <rect x="0" y="0" width="100" height="100" rx="22" fill="#0D1B2A"/>
            <circle cx="50" cy="50" r="28" fill="none" stroke="url(#loginGrad)" strokeWidth="14" mask="url(#loginMask)"/>
            <line x1="75" y1="26" x2="56" y2="26" stroke="url(#loginGrad)" strokeWidth="14" strokeLinecap="round"/>
            <circle cx="56" cy="26" r="9" fill="#F0F4F8"/>
          </svg>
          <div>
            <div className="text-3xl font-bold tracking-tight text-white leading-none">
              Gov<span className="text-teal">AI</span>
            </div>
            <div className="text-sm text-mgray mt-1">Platforma Zarządzania Agentami AI</div>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs text-mgray/70 mb-1.5 uppercase tracking-wider font-semibold">
              Adres e-mail
            </label>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              autoFocus
              className="w-full px-4 py-2.5 rounded-lg bg-dark border border-blue/40
                         text-white placeholder-mgray/30 focus:outline-none
                         focus:border-teal focus:ring-1 focus:ring-teal/50 transition-colors"
              placeholder="uzytkownik@kancelaria.local"
            />
          </div>

          <div>
            <label className="block text-xs text-mgray/70 mb-1.5 uppercase tracking-wider font-semibold">
              Hasło
            </label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              className="w-full px-4 py-2.5 rounded-lg bg-dark border border-blue/40
                         text-white placeholder-mgray/30 focus:outline-none
                         focus:border-teal focus:ring-1 focus:ring-teal/50 transition-colors"
              placeholder="••••••••••••"
            />
          </div>

          {error && (
            <div className="px-4 py-3 rounded-lg bg-govred/10 border border-govred/40 text-red-300 text-sm">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 rounded-lg bg-blue hover:bg-teal
                       disabled:opacity-50 disabled:cursor-not-allowed
                       text-white font-semibold transition-colors mt-2"
          >
            {loading ? 'Logowanie...' : 'Zaloguj się'}
          </button>
        </form>

        <div className="mt-6 pt-5 border-t border-blue/30 text-center text-xs text-mgray/40">
          EU AI Act Compliance Platform · v0.4.0
        </div>
      </div>
    </div>
  );
}
