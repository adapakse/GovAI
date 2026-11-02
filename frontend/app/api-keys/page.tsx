'use client';

import { useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { api, Agent, ApiKey, ApiKeyCreated } from '@/lib/api';
import { useAuth } from '@/components/AuthProvider';
import SecretModal, { ConfirmModal } from '@/components/SecretModal';
import { useFormat } from '@/lib/format';

const INPUT = 'w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal';

// Terminy ważności w dniach; 0 = bezterminowo
const EXPIRY_OPTIONS = [30, 90, 180, 365, 0] as const;

type KeyState = 'active' | 'expired' | 'revoked';

function keyState(k: ApiKey): KeyState {
  if (!k.active) return 'revoked';
  if (k.expires_at && new Date(k.expires_at).getTime() < Date.now()) return 'expired';
  return 'active';
}

const STATE_STYLE: Record<KeyState, string> = {
  active:  'text-green-400 border-green-800 bg-green-900/20',
  expired: 'text-orange-300 border-orange-800 bg-orange-900/20',
  revoked: 'text-mgray/60 border-mgray/30 bg-mgray/5',
};

// ── Formularz tworzenia ───────────────────────────────────────────────────────

function CreateKeyForm({ agents, onCreated }: { agents: Agent[]; onCreated: (k: ApiKeyCreated) => void }) {
  const t = useTranslations('admin.apiKeys');
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [name, setName] = useState('');
  const [agentId, setAgentId] = useState('');
  const [expiry, setExpiry] = useState<number>(365);

  async function save() {
    setSaving(true);
    setError('');
    try {
      const created = await api.apiKeys.create({
        name: name.trim(),
        agent_id: agentId || null,
        expires_days: expiry || null,
      });
      setOpen(false);
      setName('');
      setAgentId('');
      setExpiry(365);
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
          <label className="text-xs text-mgray mb-1 block">{t('form.name')}</label>
          <input className={INPUT} value={name} placeholder={t('form.namePlaceholder')}
            onChange={e => setName(e.target.value)} />
        </div>
        <div>
          <label className="text-xs text-mgray mb-1 block">{t('form.agent')}</label>
          <select className={INPUT} value={agentId} onChange={e => setAgentId(e.target.value)}>
            <option value="">{t('form.anyAgent')}</option>
            {agents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-mgray mb-1 block">{t('form.expiry')}</label>
          <select className={INPUT} value={expiry} onChange={e => setExpiry(Number(e.target.value))}>
            {EXPIRY_OPTIONS.map(d => (
              <option key={d} value={d}>{d ? t('form.expiryDays', { days: d }) : t('form.noExpiry')}</option>
            ))}
          </select>
        </div>
      </div>
      <p className="text-xs text-mgray/60">{agentId ? t('form.agentHint') : t('form.anyAgentHint')}</p>
      {error && <div className="text-sm text-red-300">{error}</div>}
      <div className="flex gap-3">
        <button
          onClick={save}
          disabled={saving || !name.trim()}
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

export default function ApiKeysPage() {
  const t = useTranslations('admin.apiKeys');
  const fmt = useFormat();
  const { user } = useAuth();
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<ApiKey | null>(null);
  const [revoking, setRevoking] = useState(false);
  const [showRevoked, setShowRevoked] = useState(false);

  const isOrgAdmin = user?.role === 'partner' || user?.role === 'it_admin';

  async function load() {
    setLoading(true);
    try {
      const [k, a] = await Promise.all([api.apiKeys.list(), api.agents.list()]);
      setKeys(k);
      setAgents(a);
      setError('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { if (isOrgAdmin) load(); else setLoading(false); }, [isOrgAdmin]);

  async function revoke(k: ApiKey) {
    setRevoking(true);
    try {
      await api.apiKeys.revoke(k.id);
      setRevokeTarget(null);
      await load();
    } catch (e) {
      setRevokeTarget(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRevoking(false);
    }
  }

  if (user && !isOrgAdmin) {
    return <div className="text-mgray py-12 text-center">{t('noAccess')}</div>;
  }

  const revokedCount = keys.filter(k => !k.active).length;
  const visible = showRevoked ? keys : keys.filter(k => k.active);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">{t('title')}</h1>
        <p className="text-mgray text-sm mt-1">{t('subtitle')}</p>
      </div>

      <CreateKeyForm agents={agents} onCreated={k => { setCreated(k); load(); }} />

      {error && (
        <div className="px-4 py-3 rounded-lg bg-govred/10 border border-govred/40 text-red-300 text-sm flex justify-between gap-4">
          <span>{error}</span>
          <button onClick={() => setError('')} className="text-red-300/70 hover:text-red-200">✕</button>
        </div>
      )}

      {revokedCount > 0 && (
        <label className="flex items-center gap-2 text-xs text-mgray cursor-pointer select-none">
          <input type="checkbox" checked={showRevoked} onChange={e => setShowRevoked(e.target.checked)} />
          {t('showRevoked', { count: revokedCount })}
        </label>
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
                <th className="text-left px-4 py-2.5">{t('columns.name')}</th>
                <th className="text-left px-4 py-2.5">{t('columns.prefix')}</th>
                <th className="text-left px-4 py-2.5">{t('columns.agent')}</th>
                <th className="text-left px-4 py-2.5">{t('columns.expires')}</th>
                <th className="text-left px-4 py-2.5">{t('columns.lastUsed')}</th>
                <th className="text-left px-4 py-2.5">{t('columns.status')}</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {visible.map(k => {
                const state = keyState(k);
                return (
                  <tr key={k.id} className="border-t border-blue/15 hover:bg-blue/5">
                    <td className="px-4 py-2.5">
                      <div className="text-white font-medium">{k.name}</div>
                      <div className="text-xs text-mgray/50">{t('createdAt', { date: fmt.date(k.created_at) })}</div>
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-teal/80">{k.key_prefix}…</td>
                    <td className="px-4 py-2.5 text-xs">
                      {k.agent_name ?? (k.agent_id ? k.agent_id : <span className="text-mgray/50 italic">{t('anyAgent')}</span>)}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-mgray/70">
                      {k.expires_at ? fmt.date(k.expires_at) : t('noExpiry')}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-mgray/70">
                      {k.last_used_at ? fmt.dateTime(k.last_used_at) : t('neverUsed')}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`text-xs font-bold px-2 py-0.5 rounded border ${STATE_STYLE[state]}`}>
                        {t(`state.${state}`)}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      {k.active && (
                        <button
                          onClick={() => setRevokeTarget(k)}
                          className="text-xs text-red-400/70 hover:text-red-300 border border-red-900/30 px-3 py-1 rounded transition-colors"
                        >
                          {t('revoke')}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {revokeTarget && (
        <ConfirmModal
          title={t('revokeConfirm.title')}
          message={t('revokeConfirm.message', { name: revokeTarget.name })}
          confirmLabel={t('revokeConfirm.confirm')}
          danger
          busy={revoking}
          onConfirm={() => revoke(revokeTarget)}
          onCancel={() => setRevokeTarget(null)}
        />
      )}

      {created && (
        <SecretModal
          title={t('secret.title')}
          description={t('secret.description', { name: created.name })}
          label={t('secret.label')}
          secret={created.key}
          onClose={() => setCreated(null)}
        />
      )}
    </div>
  );
}
