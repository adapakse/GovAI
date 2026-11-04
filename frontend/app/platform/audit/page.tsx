'use client';

import { useEffect, useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import { api, PlatformAuditEntry } from '@/lib/api';
import { useAuth } from '@/components/AuthProvider';
import SearchBox from '@/components/SearchBox';
import { matchesQuery } from '@/lib/search';
import { useFormat } from '@/lib/format';

const LIMITS = [100, 500, 1000] as const;

// Klucz etykiety akcji: "tenant.create" → actions.tenant_create (brak tłumaczenia → surowy kod)
const actionKey = (action: string) => `actions.${action.replace(/[^A-Za-z0-9]/g, '_')}`;

export default function PlatformAuditPage() {
  const t = useTranslations('platform.audit');
  const fmt = useFormat();
  const { user } = useAuth();
  const [entries, setEntries] = useState<PlatformAuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [limit, setLimit] = useState<number>(100);

  const isSuperAdmin = user?.is_super_admin === true && !user?.acting_as;

  useEffect(() => {
    if (!isSuperAdmin) { setLoading(false); return; }
    setLoading(true);
    api.platform.audit(limit)
      .then(e => { setEntries(e); setError(''); })
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [isSuperAdmin, limit]);

  const label = (action: string) => (t.has(actionKey(action)) ? t(actionKey(action)) : action);

  const visible = useMemo(() => entries.filter(e => matchesQuery(
    [e.actor_email, e.action, label(e.action), e.tenant_name, e.tenant_slug, e.details ? JSON.stringify(e.details) : ''],
    query,
  )), [entries, query]);

  if (user && !isSuperAdmin) {
    return <div className="text-mgray py-12 text-center">{t('noAccess')}</div>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">{t('title')}</h1>
        <p className="text-mgray text-sm mt-1">{t('subtitle')}</p>
      </div>

      <div className="flex items-center gap-4 flex-wrap">
        <SearchBox value={query} onChange={setQuery} placeholder={t('searchPlaceholder')}
          count={visible.length} total={entries.length} />
        <label className="flex items-center gap-2 text-xs text-mgray">
          {t('limit')}
          <select className="bg-navy border border-blue/30 rounded px-2 py-1 text-xs text-white"
            value={limit} onChange={e => setLimit(Number(e.target.value))}>
            {LIMITS.map(l => <option key={l} value={l}>{l}</option>)}
          </select>
        </label>
      </div>

      {error && (
        <div className="px-4 py-3 rounded-lg bg-govred/10 border border-govred/40 text-red-300 text-sm">{error}</div>
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
                <th className="text-left px-4 py-2.5">{t('columns.time')}</th>
                <th className="text-left px-4 py-2.5">{t('columns.actor')}</th>
                <th className="text-left px-4 py-2.5">{t('columns.action')}</th>
                <th className="text-left px-4 py-2.5">{t('columns.tenant')}</th>
                <th className="text-left px-4 py-2.5">{t('columns.details')}</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((e, i) => (
                <tr key={e.id ?? `${e.time}-${i}`} className="border-t border-blue/15 align-top hover:bg-blue/5">
                  <td className="px-4 py-2.5 text-xs text-mgray/80 whitespace-nowrap">{fmt.dateTime(e.time)}</td>
                  <td className="px-4 py-2.5 text-xs">{e.actor_email}</td>
                  <td className="px-4 py-2.5">
                    <span className="text-xs font-semibold text-teal" title={e.action}>{label(e.action)}</span>
                  </td>
                  <td className="px-4 py-2.5 text-xs">
                    {e.tenant_name ? (
                      <>
                        <div className="text-white">{e.tenant_name}</div>
                        <div className="text-mgray/50 font-mono">{e.tenant_slug}</div>
                      </>
                    ) : e.tenant_id ? <span className="font-mono text-mgray/60">{e.tenant_id}</span> : '—'}
                  </td>
                  <td className="px-4 py-2.5">
                    {e.details && Object.keys(e.details).length > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        {Object.entries(e.details).map(([k, v]) => (
                          <span key={k} className="text-[11px] font-mono bg-blue/10 border border-blue/20 text-blue-200 px-1.5 py-0.5 rounded">
                            {k}: {typeof v === 'string' ? v : JSON.stringify(v)}
                          </span>
                        ))}
                      </div>
                    ) : <span className="text-mgray/40">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
