'use client';

import { useEffect, useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import {
  api, generateTemporaryPassword, OrgUser, USER_ROLES, USER_STATUSES, UserRole, UserStatus,
} from '@/lib/api';
import { useAuth } from '@/components/AuthProvider';
import SearchBox from '@/components/SearchBox';
import SecretModal, { ConfirmModal } from '@/components/SecretModal';
import { matchesQuery } from '@/lib/search';
import { useFormat } from '@/lib/format';

const INPUT = 'w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal';
const SELECT_SM = 'bg-navy border border-blue/30 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-teal disabled:opacity-50';

const STATUS_STYLE: Record<UserStatus, string> = {
  active:    'text-green-400',
  suspended: 'text-red-400',
  pending:   'text-orange-300',
};

interface Secret { email: string; password: string }

// ── Formularz dodawania ───────────────────────────────────────────────────────

function AddUserForm({ roles, onCreated }: { roles: readonly UserRole[]; onCreated: (s: Secret | null) => void }) {
  const t = useTranslations('admin.users');
  const tr = useTranslations('shell.roles');
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [form, setForm] = useState({ email: '', full_name: '', role: 'associate' as UserRole });

  async function save() {
    setSaving(true);
    setError('');
    try {
      const created = await api.users.create({
        email: form.email.trim(), full_name: form.full_name.trim(), role: form.role,
      });
      setOpen(false);
      setForm({ email: '', full_name: '', role: 'associate' });
      onCreated(created.temporary_password ? { email: created.email, password: created.temporary_password } : null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="px-4 py-2 border border-dashed border-blue/40 text-teal text-sm rounded-lg hover:border-teal/60 hover:bg-teal/5 transition-colors"
      >
        {t('add')}
      </button>
    );
  }

  return (
    <div className="bg-dark/60 border border-blue/30 rounded-xl p-5 space-y-4">
      <div className="font-semibold text-white text-sm">{t('form.title')}</div>
      <div className="grid grid-cols-3 gap-4">
        <div>
          <label className="text-xs text-mgray mb-1 block">{t('form.email')}</label>
          <input type="email" className={INPUT} value={form.email}
            onChange={e => setForm(f => ({ ...f, email: e.target.value }))} />
        </div>
        <div>
          <label className="text-xs text-mgray mb-1 block">{t('form.fullName')}</label>
          <input className={INPUT} value={form.full_name}
            onChange={e => setForm(f => ({ ...f, full_name: e.target.value }))} />
        </div>
        <div>
          <label className="text-xs text-mgray mb-1 block">{t('form.role')}</label>
          <select className={INPUT} value={form.role}
            onChange={e => setForm(f => ({ ...f, role: e.target.value as UserRole }))}>
            {roles.map(r => <option key={r} value={r}>{tr(r)}</option>)}
          </select>
        </div>
      </div>
      <p className="text-xs text-mgray/60">{t('form.passwordHint')}</p>
      {error && <div className="text-sm text-red-300">{error}</div>}
      <div className="flex gap-3">
        <button
          onClick={save}
          disabled={saving || !form.email.includes('@') || !form.full_name.trim()}
          className="px-4 py-2 bg-teal text-dark text-sm font-semibold rounded-lg hover:bg-teal/90 disabled:opacity-40"
        >
          {saving ? t('form.saving') : t('form.save')}
        </button>
        <button onClick={() => { setOpen(false); setError(''); }}
          className="px-4 py-2 text-mgray text-sm border border-blue/30 rounded-lg hover:bg-blue/10">
          {t('form.cancel')}
        </button>
      </div>
    </div>
  );
}

// ── Strona ────────────────────────────────────────────────────────────────────

export default function UsersPage() {
  const t = useTranslations('admin.users');
  const tr = useTranslations('shell.roles');
  const fmt = useFormat();
  const { user } = useAuth();
  const [users, setUsers] = useState<OrgUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [secret, setSecret] = useState<Secret | null>(null);
  const [created, setCreated] = useState(false);
  const [resetTarget, setResetTarget] = useState<OrgUser | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const isOrgAdmin = user?.role === 'partner' || user?.role === 'it_admin';
  // it_admin nie nadaje roli partner i nie edytuje partnerów (API zwraca 403)
  const assignableRoles: readonly UserRole[] = user?.role === 'it_admin' ? USER_ROLES.filter(r => r !== 'partner') : USER_ROLES;

  async function load() {
    setLoading(true);
    try {
      setUsers(await api.users.list());
      setError('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { if (isOrgAdmin) load(); else setLoading(false); }, [isOrgAdmin]);

  const visible = useMemo(() => users.filter(u => matchesQuery(
    [u.full_name, u.email, u.role, tr.has(u.role) ? tr(u.role) : '', u.status],
    query,
  )), [users, query]);

  async function update(target: OrgUser, body: { role?: UserRole; status?: UserStatus }) {
    setBusy(target.id);
    try {
      await api.users.update(target.id, body);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function resetPassword(target: OrgUser) {
    setBusy(target.id);
    try {
      const generated = generateTemporaryPassword();
      const res = await api.users.setPassword(target.id, generated);
      setResetTarget(null);
      setCreated(false);
      setSecret({ email: target.email, password: res.temporary_password ?? generated });
    } catch (e) {
      setResetTarget(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  if (user && !isOrgAdmin) {
    return <div className="text-mgray py-12 text-center">{t('noAccess')}</div>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">{t('title')}</h1>
        <p className="text-mgray text-sm mt-1">{t('subtitle', { tenant: user?.tenant?.name ?? '' })}</p>
      </div>

      <AddUserForm
        roles={assignableRoles}
        onCreated={s => { load(); if (s) { setCreated(true); setSecret(s); } }}
      />

      {error && (
        <div className="px-4 py-3 rounded-lg bg-govred/10 border border-govred/40 text-red-300 text-sm flex justify-between gap-4">
          <span>{error}</span>
          <button onClick={() => setError('')} className="text-red-300/70 hover:text-red-200">✕</button>
        </div>
      )}

      {users.length > 0 && (
        <SearchBox value={query} onChange={setQuery} placeholder={t('searchPlaceholder')}
          count={visible.length} total={users.length} />
      )}

      {loading ? (
        <div className="text-mgray animate-pulse py-8">{t('loading')}</div>
      ) : users.length === 0 ? (
        <div className="text-center py-12 text-mgray/40">{t('empty')}</div>
      ) : (
        <div className="border border-blue/30 rounded-xl overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-dark/60 text-xs text-mgray uppercase tracking-wider">
              <tr>
                <th className="text-left px-4 py-2.5">{t('columns.user')}</th>
                <th className="text-left px-4 py-2.5">{t('columns.role')}</th>
                <th className="text-left px-4 py-2.5">{t('columns.status')}</th>
                <th className="text-left px-4 py-2.5">{t('columns.lastLogin')}</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {visible.map(u => {
                const self = u.id === user?.id;
                const locked = self || (user?.role === 'it_admin' && u.role === 'partner') || busy === u.id;
                return (
                  <tr key={u.id} className="border-t border-blue/15 hover:bg-blue/5">
                    <td className="px-4 py-2.5">
                      <div className="text-white font-medium">{u.full_name}{self && <span className="text-mgray/50 font-normal"> {t('you')}</span>}</div>
                      <div className="text-xs text-mgray/60">{u.email}</div>
                    </td>
                    <td className="px-4 py-2.5">
                      <select className={SELECT_SM} value={u.role} disabled={locked}
                        onChange={e => update(u, { role: e.target.value as UserRole })}>
                        {/* bieżąca rola zawsze na liście, nawet gdy jej nadawanie jest niedozwolone */}
                        {USER_ROLES.filter(r => r === u.role || assignableRoles.includes(r)).map(r =>
                          <option key={r} value={r}>{tr(r)}</option>)}
                      </select>
                    </td>
                    <td className="px-4 py-2.5">
                      <select className={`${SELECT_SM} ${STATUS_STYLE[u.status] ?? ''}`} value={u.status} disabled={locked}
                        onChange={e => update(u, { status: e.target.value as UserStatus })}>
                        {USER_STATUSES.map(s => <option key={s} value={s}>{t(`status.${s}`)}</option>)}
                      </select>
                    </td>
                    <td className="px-4 py-2.5 text-xs text-mgray/70">
                      {u.last_login_at ? fmt.dateTime(u.last_login_at) : t('never')}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <button
                        onClick={() => setResetTarget(u)}
                        disabled={locked}
                        className="text-xs text-mgray hover:text-white border border-blue/20 px-3 py-1 rounded transition-colors disabled:opacity-30"
                      >
                        {t('resetPassword')}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {resetTarget && (
        <ConfirmModal
          title={t('resetConfirm.title')}
          message={t('resetConfirm.message', { name: resetTarget.full_name, email: resetTarget.email })}
          confirmLabel={t('resetConfirm.confirm')}
          busy={busy === resetTarget.id}
          onConfirm={() => resetPassword(resetTarget)}
          onCancel={() => setResetTarget(null)}
        />
      )}

      {secret && (
        <SecretModal
          title={created ? t('secret.createdTitle') : t('secret.resetTitle')}
          description={t('secret.description', { email: secret.email })}
          label={t('secret.label')}
          secret={secret.password}
          onClose={() => setSecret(null)}
        />
      )}
    </div>
  );
}
