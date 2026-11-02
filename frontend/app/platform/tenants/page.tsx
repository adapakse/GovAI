'use client';

import { useEffect, useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import { api, PlatformTenant, TenantCreated, TenantUser } from '@/lib/api';
import { apiMe, enterTenantSession } from '@/lib/auth';
import { LOCALES, LOCALE_NAMES } from '@/i18n/locales';
import { useAuth } from '@/components/AuthProvider';
import SearchBox from '@/components/SearchBox';
import SecretModal, { ConfirmModal, Modal } from '@/components/SecretModal';
import { matchesQuery } from '@/lib/search';
import { useFormat } from '@/lib/format';

const INPUT = 'w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal';
const BTN_SM = 'text-xs border px-2.5 py-1 rounded transition-colors disabled:opacity-30 whitespace-nowrap';

// Zgodne z api/services/tenant_host.py (is_valid_slug, RESERVED_SLUGS)
const SLUG_RE = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/;
const RESERVED_SLUGS = new Set([
  'app', 'api', 'www', 'admin', 'int', 'staging', 'stage', 'dev', 'test', 'preview',
  'mail', 'smtp', 'imap', 'ftp', 'static', 'cdn', 'assets', 'status', 'docs', 'gateway',
]);

type SlugProblem = 'chars' | 'edges' | 'length' | 'reserved' | 'taken';

function slugProblem(slug: string, taken: Set<string>): SlugProblem | null {
  if (!slug) return null;
  if (/[^a-z0-9-]/.test(slug)) return 'chars';
  if (!SLUG_RE.test(slug)) return 'edges';
  if (slug.length > 63) return 'length';
  if (RESERVED_SLUGS.has(slug)) return 'reserved';
  if (taken.has(slug)) return 'taken';
  return null;
}

type TenantState = 'active' | 'suspended' | 'deleted';

function tenantState(t: PlatformTenant): TenantState {
  if (t.deleted_at) return 'deleted';
  return t.status === 'suspended' ? 'suspended' : 'active';
}

const STATE_STYLE: Record<TenantState, string> = {
  active:    'text-green-400 border-green-800 bg-green-900/20',
  suspended: 'text-orange-300 border-orange-800 bg-orange-900/20',
  deleted:   'text-mgray/60 border-mgray/30 bg-mgray/5',
};

// ── Formularz zakładania organizacji ──────────────────────────────────────────

const EMPTY_FORM = { slug: '', name: '', default_locale: '', admin_email: '', admin_full_name: '' };

function CreateTenantForm({ taken, onCreated }: { taken: Set<string>; onCreated: (r: TenantCreated) => void }) {
  const t = useTranslations('platform.tenants');
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [form, setForm] = useState(EMPTY_FORM);

  const problem = slugProblem(form.slug, taken);
  const valid = !!form.slug && !problem && !!form.name.trim()
    && form.admin_email.includes('@') && !!form.admin_full_name.trim();

  async function save() {
    setSaving(true);
    setError('');
    try {
      const created = await api.platform.createTenant({
        slug: form.slug,
        name: form.name.trim(),
        ...(form.default_locale ? { default_locale: form.default_locale } : {}),
        admin_email: form.admin_email.trim(),
        admin_full_name: form.admin_full_name.trim(),
      });
      setOpen(false);
      setForm(EMPTY_FORM);
      onCreated(created);
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
          <label className="text-xs text-mgray mb-1 block">{t('form.slug')}</label>
          <input
            className={`${INPUT} font-mono ${problem ? 'border-govred/70 focus:border-govred' : ''}`}
            value={form.slug}
            placeholder="kancelaria-nowak"
            maxLength={63}
            onChange={e => setForm(f => ({ ...f, slug: e.target.value.trim() }))}
          />
          <p className={`text-xs mt-1 ${problem ? 'text-red-300' : 'text-mgray/50'}`}>
            {problem ? t(`form.slugErrors.${problem}`) : form.slug ? t('form.slugPreview', { slug: form.slug }) : t('form.slugHint')}
          </p>
        </div>
        <div>
          <label className="text-xs text-mgray mb-1 block">{t('form.name')}</label>
          <input className={INPUT} value={form.name} placeholder={t('form.namePlaceholder')}
            onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
        </div>
        <div>
          <label className="text-xs text-mgray mb-1 block">{t('form.locale')}</label>
          <select className={INPUT} value={form.default_locale}
            onChange={e => setForm(f => ({ ...f, default_locale: e.target.value }))}>
            <option value="">{t('form.localePlatform')}</option>
            {LOCALES.map(l => <option key={l} value={l}>{LOCALE_NAMES[l]}</option>)}
          </select>
        </div>
      </div>
      <div className="text-xs text-mgray uppercase tracking-wider font-semibold pt-1">{t('form.adminSection')}</div>
      <div className="grid grid-cols-3 gap-4">
        <div>
          <label className="text-xs text-mgray mb-1 block">{t('form.adminEmail')}</label>
          <input type="email" className={INPUT} value={form.admin_email}
            onChange={e => setForm(f => ({ ...f, admin_email: e.target.value }))} />
        </div>
        <div>
          <label className="text-xs text-mgray mb-1 block">{t('form.adminFullName')}</label>
          <input className={INPUT} value={form.admin_full_name}
            onChange={e => setForm(f => ({ ...f, admin_full_name: e.target.value }))} />
        </div>
      </div>
      <p className="text-xs text-mgray/60">{t('form.adminHint')}</p>
      {error && <div className="text-sm text-red-300">{error}</div>}
      <div className="flex gap-3">
        <button
          onClick={save}
          disabled={saving || !valid}
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

// ── Usuwanie — potwierdzenie przez wpisanie sluga ─────────────────────────────

function DeleteTenantModal({ tenant, onDeleted, onCancel }: {
  tenant: PlatformTenant; onDeleted: () => void; onCancel: () => void;
}) {
  const t = useTranslations('platform.tenants.delete');
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function remove() {
    setBusy(true);
    setError('');
    try {
      await api.platform.deleteTenant(tenant.id);
      onDeleted();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <Modal title={t('title', { name: tenant.name })} onClose={onCancel}>
      <div className="space-y-4">
        <p className="text-sm text-mgray">{t('message')}</p>
        <div>
          <label className="text-xs text-mgray mb-1 block">
            {t.rich('typeSlug', { slug: tenant.slug, code: (c) => <code className="text-white font-mono">{c}</code> })}
          </label>
          <input className={`${INPUT} font-mono`} value={typed} autoFocus
            onChange={e => setTyped(e.target.value)} />
        </div>
        {error && <div className="text-sm text-red-300">{error}</div>}
        <div className="flex justify-end gap-3">
          <button onClick={onCancel}
            className="px-4 py-2 text-mgray text-sm border border-blue/30 rounded-lg hover:bg-blue/10">
            {t('cancel')}
          </button>
          <button
            onClick={remove}
            disabled={busy || typed !== tenant.slug}
            className="px-4 py-2 bg-govred text-white text-sm font-semibold rounded-lg hover:bg-govred/80 disabled:opacity-40"
          >
            {busy ? '...' : t('confirm')}
          </button>
        </div>
      </div>
    </Modal>
  );
}

// ── Użytkownicy organizacji ───────────────────────────────────────────────────

function TenantUsersModal({ tenant, onClose }: { tenant: PlatformTenant; onClose: () => void }) {
  const t = useTranslations('platform.tenants.users');
  const tr = useTranslations('shell.roles');
  const ts = useTranslations('admin.users.status');
  const fmt = useFormat();
  const [users, setUsers] = useState<TenantUser[] | null>(null);
  const [error, setError] = useState('');
  const [resetTarget, setResetTarget] = useState<TenantUser | null>(null);
  const [busy, setBusy] = useState(false);
  const [secret, setSecret] = useState<{ email: string; password: string } | null>(null);

  useEffect(() => {
    api.platform.tenantUsers(tenant.id)
      .then(setUsers)
      .catch(e => { setUsers([]); setError(e instanceof Error ? e.message : String(e)); });
  }, [tenant.id]);

  async function reset(u: TenantUser) {
    setBusy(true);
    try {
      const res = await api.platform.resetPassword(tenant.id, u.id);
      setResetTarget(null);
      setSecret({ email: u.email, password: res.temporary_password });
    } catch (e) {
      setResetTarget(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Modal title={t('title', { name: tenant.name })} onClose={onClose} wide>
        {error && <div className="mb-3 text-sm text-red-300">{error}</div>}
        {users === null ? (
          <div className="text-mgray animate-pulse py-6">{t('loading')}</div>
        ) : users.length === 0 ? (
          <div className="text-mgray/50 py-6 text-center">{t('empty')}</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-xs text-mgray uppercase tracking-wider">
              <tr>
                <th className="text-left py-2">{t('columns.user')}</th>
                <th className="text-left py-2">{t('columns.role')}</th>
                <th className="text-left py-2">{t('columns.status')}</th>
                <th className="text-left py-2">{t('columns.lastLogin')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id} className="border-t border-blue/15">
                  <td className="py-2 pr-3">
                    <div className="text-white">{u.full_name}</div>
                    <div className="text-xs text-mgray/60">{u.email}</div>
                  </td>
                  <td className="py-2 pr-3 text-xs">{tr.has(u.role) ? tr(u.role) : u.role}</td>
                  <td className="py-2 pr-3 text-xs">{ts.has(u.status) ? ts(u.status) : u.status}</td>
                  <td className="py-2 pr-3 text-xs text-mgray/70">
                    {u.last_login_at ? fmt.dateTime(u.last_login_at) : t('never')}
                  </td>
                  <td className="py-2 text-right">
                    <button onClick={() => setResetTarget(u)}
                      className={`${BTN_SM} text-mgray hover:text-white border-blue/20`}>
                      {t('resetPassword')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Modal>

      {resetTarget && (
        <ConfirmModal
          title={t('resetConfirm.title')}
          message={t('resetConfirm.message', { name: resetTarget.full_name, email: resetTarget.email })}
          confirmLabel={t('resetConfirm.confirm')}
          busy={busy}
          onConfirm={() => reset(resetTarget)}
          onCancel={() => setResetTarget(null)}
        />
      )}

      {secret && (
        <SecretModal
          title={t('secret.title')}
          description={t('secret.description', { email: secret.email })}
          label={t('secret.label')}
          secret={secret.password}
          onClose={() => setSecret(null)}
        />
      )}
    </>
  );
}

// ── Strona ────────────────────────────────────────────────────────────────────

export default function PlatformTenantsPage() {
  const t = useTranslations('platform.tenants');
  const fmt = useFormat();
  const { user } = useAuth();
  const [tenants, setTenants] = useState<PlatformTenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [showDeleted, setShowDeleted] = useState(false);
  const [created, setCreated] = useState<TenantCreated | null>(null);
  const [usersOf, setUsersOf] = useState<PlatformTenant | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<PlatformTenant | null>(null);
  const [suspendTarget, setSuspendTarget] = useState<PlatformTenant | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [actingExpired, setActingExpired] = useState(false);

  // Powrót po wygaśnięciu tokenu wejścia do organizacji (lib/auth.ts ACTING_EXPIRED_URL)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('actingExpired')) {
      setActingExpired(true);
      window.history.replaceState(null, '', window.location.pathname);
    }
  }, []);

  const isSuperAdmin = user?.is_super_admin === true && !user?.acting_as;

  async function load() {
    setLoading(true);
    try {
      setTenants(await api.platform.tenants());
      setError('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { if (isSuperAdmin) load(); else setLoading(false); }, [isSuperAdmin]);

  // Slug zajęty także przez organizację usuniętą (unikalność w bazie)
  const taken = useMemo(() => new Set(tenants.map(x => x.slug)), [tenants]);
  const deletedCount = tenants.filter(x => x.deleted_at).length;
  const visible = useMemo(() => tenants
    .filter(x => showDeleted || !x.deleted_at)
    .filter(x => matchesQuery([x.name, x.slug], query)), [tenants, showDeleted, query]);

  async function setStatus(tenant: PlatformTenant, status: 'active' | 'suspended') {
    setBusy(tenant.id);
    try {
      await api.platform.updateTenant(tenant.id, { status });
      setSuspendTarget(null);
      await load();
    } catch (e) {
      setSuspendTarget(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function enter(tenant: PlatformTenant) {
    setBusy(tenant.id);
    try {
      const { access_token } = await api.platform.enter(tenant.id);
      enterTenantSession(access_token);
      // Zapisany użytkownik = kontekst organizacji docelowej (pasek "Działasz jako...")
      await apiMe();
      window.location.href = '/dashboard';
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(null);
    }
  }

  if (user && !isSuperAdmin) {
    return <div className="text-mgray py-12 text-center">{t('noAccess')}</div>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">{t('title')}</h1>
        <p className="text-mgray text-sm mt-1">{t('subtitle')}</p>
      </div>

      {actingExpired && (
        <div className="px-4 py-3 rounded-lg bg-orange-900/20 border border-orange-700/50 text-orange-200 text-sm flex justify-between gap-4">
          <span>{t('actingExpired')}</span>
          <button onClick={() => setActingExpired(false)} className="text-orange-200/70 hover:text-orange-100">✕</button>
        </div>
      )}

      <CreateTenantForm taken={taken} onCreated={r => { setCreated(r); load(); }} />

      {error && (
        <div className="px-4 py-3 rounded-lg bg-govred/10 border border-govred/40 text-red-300 text-sm flex justify-between gap-4">
          <span>{error}</span>
          <button onClick={() => setError('')} className="text-red-300/70 hover:text-red-200">✕</button>
        </div>
      )}

      {tenants.length > 0 && (
        <div className="flex items-center gap-4 flex-wrap">
          <SearchBox value={query} onChange={setQuery} placeholder={t('searchPlaceholder')}
            count={visible.length} total={tenants.length} />
          {deletedCount > 0 && (
            <label className="flex items-center gap-2 text-xs text-mgray cursor-pointer select-none">
              <input type="checkbox" checked={showDeleted} onChange={e => setShowDeleted(e.target.checked)} />
              {t('showDeleted', { count: deletedCount })}
            </label>
          )}
        </div>
      )}

      {loading ? (
        <div className="text-mgray animate-pulse py-8">{t('loading')}</div>
      ) : visible.length === 0 ? (
        <div className="text-center py-12 text-mgray/40">{t('empty')}</div>
      ) : (
        <div className="border border-blue/30 rounded-xl overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-dark/60 text-xs text-mgray uppercase tracking-wider">
              <tr>
                <th className="text-left px-4 py-2.5">{t('columns.tenant')}</th>
                <th className="text-left px-4 py-2.5">{t('columns.status')}</th>
                <th className="text-right px-4 py-2.5">{t('columns.users')}</th>
                <th className="text-right px-4 py-2.5">{t('columns.agents')}</th>
                <th className="text-left px-4 py-2.5">{t('columns.created')}</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {visible.map(x => {
                const state = tenantState(x);
                const own = x.id === user?.tenant?.id;
                const rowBusy = busy === x.id;
                return (
                  <tr key={x.id} className={`border-t border-blue/15 hover:bg-blue/5 ${state === 'deleted' ? 'opacity-50' : ''}`}>
                    <td className="px-4 py-2.5">
                      <div className="text-white font-medium flex items-center gap-2">
                        {x.name}
                        {x.is_demo && (
                          <span className="text-[10px] font-bold px-1.5 py-0.5 rounded border border-purple-800 text-purple-300 bg-purple-900/20 uppercase">
                            {t('demo')}
                          </span>
                        )}
                        {own && <span className="text-mgray/50 text-xs font-normal">{t('own')}</span>}
                      </div>
                      <div className="text-xs text-mgray/60 font-mono">{x.slug}</div>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`text-xs font-bold px-2 py-0.5 rounded border ${STATE_STYLE[state]}`}>
                        {t(`state.${state}`)}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{fmt.number(Number(x.users_count))}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{fmt.number(Number(x.agents_count))}</td>
                    <td className="px-4 py-2.5 text-xs text-mgray/70">{fmt.date(x.created_at)}</td>
                    <td className="px-4 py-2.5">
                      {state !== 'deleted' && (
                        <div className="flex gap-1.5 justify-end">
                          <button onClick={() => setUsersOf(x)}
                            className={`${BTN_SM} text-mgray hover:text-white border-blue/20`}>
                            {t('actions.users')}
                          </button>
                          {!own && (
                            <button onClick={() => enter(x)} disabled={rowBusy || state !== 'active'}
                              title={state !== 'active' ? t('actions.enterSuspended') : undefined}
                              className={`${BTN_SM} text-teal border-teal/40 hover:bg-teal/10`}>
                              {t('actions.enter')}
                            </button>
                          )}
                          {state === 'active' ? (
                            <button onClick={() => setSuspendTarget(x)} disabled={rowBusy || own}
                              className={`${BTN_SM} text-orange-300 border-orange-900/40 hover:bg-orange-900/20`}>
                              {t('actions.suspend')}
                            </button>
                          ) : (
                            <button onClick={() => setStatus(x, 'active')} disabled={rowBusy}
                              className={`${BTN_SM} text-green-400 border-green-900/40 hover:bg-green-900/20`}>
                              {t('actions.activate')}
                            </button>
                          )}
                          <button onClick={() => setDeleteTarget(x)} disabled={rowBusy || own || x.is_demo}
                            title={x.is_demo ? t('actions.deleteDemo') : own ? t('actions.deleteOwn') : undefined}
                            className={`${BTN_SM} text-red-400/70 hover:text-red-300 border-red-900/30`}>
                            {t('actions.delete')}
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {suspendTarget && (
        <ConfirmModal
          title={t('suspendConfirm.title')}
          message={t('suspendConfirm.message', { name: suspendTarget.name })}
          confirmLabel={t('suspendConfirm.confirm')}
          danger
          busy={busy === suspendTarget.id}
          onConfirm={() => setStatus(suspendTarget, 'suspended')}
          onCancel={() => setSuspendTarget(null)}
        />
      )}

      {deleteTarget && (
        <DeleteTenantModal
          tenant={deleteTarget}
          onDeleted={() => { setDeleteTarget(null); load(); }}
          onCancel={() => setDeleteTarget(null)}
        />
      )}

      {usersOf && <TenantUsersModal tenant={usersOf} onClose={() => setUsersOf(null)} />}

      {created && (
        <SecretModal
          title={t('created.title', { name: created.tenant.name })}
          description={t('created.description', { email: created.admin.email, slug: created.tenant.slug })}
          label={t('created.label')}
          secret={created.temporary_password}
          onClose={() => setCreated(null)}
        />
      )}
    </div>
  );
}
