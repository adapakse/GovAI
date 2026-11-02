'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { useAuth } from '@/components/AuthProvider';
import { apiChangeOwnPassword, apiLogin, saveSession } from '@/lib/auth';

const MIN_LENGTH = 12;

const INPUT = `w-full px-4 py-2.5 rounded-lg bg-dark border border-blue/40 text-white placeholder-mgray/30
  focus:outline-none focus:border-teal focus:ring-1 focus:ring-teal/50 transition-colors`;

// Wymuszona zmiana hasła (hasło tymczasowe od administratora) — strona bez paska
// bocznego, jak logowanie. Dostępna też dla zwykłej zmiany hasła.
export default function ChangePasswordPage() {
  const t = useTranslations('auth.changePassword');
  const { user, logout, refreshUser } = useAuth();
  const [password, setPassword] = useState('');
  const [repeat, setRepeat] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const tooShort = password.length > 0 && password.length < MIN_LENGTH;
  const mismatch = repeat.length > 0 && password !== repeat;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (password.length < MIN_LENGTH) { setError(t('tooShort', { min: MIN_LENGTH })); return; }
    if (password !== repeat) { setError(t('mismatch')); return; }
    setError('');
    setSaving(true);
    try {
      await apiChangeOwnPassword(password);
      // API unieważnia przy zmianie hasła wszystkie sesje (refresh tokeny) —
      // logujemy się od razu nowym hasłem, żeby sesja nie wygasła za kilkadziesiąt minut.
      if (user?.email) {
        try {
          saveSession(await apiLogin(user.email, password));
        } catch { /* np. kilka organizacji pod adresem uniwersalnym — zostaje bieżący token */ }
      }
      await refreshUser();
      window.location.href = '/dashboard';
    } catch (err) {
      setError(err instanceof Error ? err.message : t('error'));
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 flex items-center justify-center bg-dark">
      <div className="w-full max-w-md p-8 rounded-2xl border border-blue/30 bg-navy shadow-2xl">
        <h1 className="text-2xl font-bold text-white">{t('title')}</h1>
        <p className="text-sm text-mgray mt-2">
          {user?.must_change_password ? t('requiredInfo') : t('info')}
        </p>
        {user && (
          <p className="text-xs text-mgray/60 mt-2">
            {user.email}{user.tenant?.name ? ` · ${user.tenant.name}` : ''}
          </p>
        )}

        <form onSubmit={handleSubmit} className="space-y-4 mt-6">
          <div>
            <label className="block text-xs text-mgray/70 mb-1.5 uppercase tracking-wider font-semibold">
              {t('newPassword')}
            </label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)}
              required autoFocus autoComplete="new-password" className={INPUT} />
            <p className={`text-xs mt-1 ${tooShort ? 'text-red-300' : 'text-mgray/50'}`}>
              {t('hint', { min: MIN_LENGTH })}
            </p>
          </div>
          <div>
            <label className="block text-xs text-mgray/70 mb-1.5 uppercase tracking-wider font-semibold">
              {t('repeatPassword')}
            </label>
            <input type="password" value={repeat} onChange={e => setRepeat(e.target.value)}
              required autoComplete="new-password" className={INPUT} />
            {mismatch && <p className="text-xs mt-1 text-red-300">{t('mismatch')}</p>}
          </div>

          {error && (
            <div className="px-4 py-3 rounded-lg bg-govred/10 border border-govred/40 text-red-300 text-sm">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={saving || password.length < MIN_LENGTH || password !== repeat}
            className="w-full py-2.5 rounded-lg bg-blue hover:bg-teal disabled:opacity-50 disabled:cursor-not-allowed
                       text-white font-semibold transition-colors mt-2"
          >
            {saving ? t('saving') : t('submit')}
          </button>
        </form>

        <div className="mt-6 pt-5 border-t border-blue/30 text-xs">
          <button onClick={logout} className="text-mgray/50 hover:text-govred transition-colors">
            {t('logout')}
          </button>
        </div>
      </div>
    </div>
  );
}
