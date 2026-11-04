'use client';

import { useCallback, useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { api, AuditEntry } from '@/lib/api';
import PolicyBadge from '@/components/PolicyBadge';
import { useFormat } from '@/lib/format';

const COLUMNS = ['time', 'agent', 'result', 'eventType', 'pii', 'latency', 'details'] as const;
const RESULTS = ['allowed', 'blocked', 'oversight_required', 'error'] as const;
const DAYS = ['1', '7', '30'] as const;

export default function AuditPage() {
  const t = useTranslations('audit');
  const tc = useTranslations('common');
  const fmt = useFormat();
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<AuditEntry | null>(null);

  const [filterResult, setFilterResult] = useState('');
  const [filterPii, setFilterPii]       = useState('');
  const [filterDays, setFilterDays]     = useState('7');

  const load = useCallback(() => {
    const params: Record<string, string> = { days: filterDays, limit: '100' };
    if (filterResult) params.policy_result = filterResult;
    if (filterPii)    params.has_pii       = filterPii;
    api.audit.list(params)
      .then(setEntries)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [filterResult, filterPii, filterDays]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">{t('header.title')}</h1>
          <p className="text-mgray text-sm mt-0.5">
            {t('header.subtitle')}
          </p>
        </div>
        <div className="text-sm text-mgray bg-navy px-3 py-1.5 rounded-full border border-blue/30">
          {t('count', { count: entries.length })}
        </div>
      </div>

      {/* Filtry */}
      <div className="flex gap-3 flex-wrap">
        <select
          value={filterResult}
          onChange={e => setFilterResult(e.target.value)}
          className="bg-navy border border-blue/40 text-sm text-white rounded-lg px-3 py-2 focus:outline-none focus:border-teal"
        >
          <option value="">{t('filters.result.all')}</option>
          {RESULTS.map(r => (
            <option key={r} value={r}>{tc(`policyResult.${r}`)}</option>
          ))}
        </select>
        <select
          value={filterPii}
          onChange={e => setFilterPii(e.target.value)}
          className="bg-navy border border-blue/40 text-sm text-white rounded-lg px-3 py-2 focus:outline-none focus:border-teal"
        >
          <option value="">{t('filters.pii.all')}</option>
          <option value="true">{t('filters.pii.with')}</option>
          <option value="false">{t('filters.pii.without')}</option>
        </select>
        <select
          value={filterDays}
          onChange={e => setFilterDays(e.target.value)}
          className="bg-navy border border-blue/40 text-sm text-white rounded-lg px-3 py-2 focus:outline-none focus:border-teal"
        >
          {DAYS.map(d => (
            <option key={d} value={d}>{t(`filters.days.${d}`)}</option>
          ))}
        </select>
      </div>

      {/* Tabela */}
      <div className="bg-navy rounded-lg border border-blue/30 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-blue/30">
              {COLUMNS.map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs uppercase tracking-wider text-mgray font-semibold">
                  {t(`table.columns.${h}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-blue/20">
            {loading && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-mgray animate-pulse">{t('table.loading')}</td></tr>
            )}
            {!loading && entries.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-mgray/50">{t('table.empty')}</td></tr>
            )}
            {entries.map((e, i) => (
              <tr key={i} className={`hover:bg-blue/10 transition-colors ${
                e.policy_result === 'blocked' ? 'bg-red-900/10' :
                e.policy_result === 'oversight_required' ? 'bg-orange-900/10' :
                e.policy_result === 'error' ? 'bg-purple-900/10' : ''
              }`}>
                <td className="px-4 py-2.5">
                  <div className="text-xs text-white font-mono">
                    {fmt.time(e.time)}
                  </div>
                  <div className="text-xs text-mgray/60">
                    {fmt.date(e.time)}
                  </div>
                </td>
                <td className="px-4 py-2.5">
                  <div className="text-xs text-white font-medium">{e.agent_name}</div>
                </td>
                <td className="px-4 py-2.5">
                  <PolicyBadge result={e.policy_result} />
                </td>
                <td className="px-4 py-2.5 text-xs text-mgray">{e.event_type}</td>
                <td className="px-4 py-2.5">
                  {e.pii_count > 0 ? (
                    <span className="text-xs text-yellow-400 font-semibold">{t('table.piiEntities', { count: e.pii_count })}</span>
                  ) : (
                    <span className="text-xs text-mgray/40">—</span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-xs text-mgray">
                  {e.latency_ms ? `${e.latency_ms} ms` : '—'}
                </td>
                <td className="px-4 py-2.5">
                  <button
                    onClick={() => setSelected(e)}
                    className="text-xs text-teal hover:underline"
                  >
                    {t('table.show')}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Modal szczegółów */}
      {selected && (
        <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4" onClick={() => setSelected(null)}>
          <div className="bg-dark border border-blue/40 rounded-xl w-full max-w-lg shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-blue/30 flex items-center justify-between">
              <h2 className="text-base font-bold text-white">{t('details.title')}</h2>
              <button onClick={() => setSelected(null)} className="text-mgray hover:text-white text-xl">×</button>
            </div>
            <div className="px-6 py-5 space-y-3 text-sm">
              {[
                [t('details.fields.agent'),         selected.agent_name],
                [t('details.fields.callId'),        selected.call_id],
                [t('details.fields.taskId'),        selected.task_id],
                [t('details.fields.result'),        selected.policy_result],
                [t('details.fields.eventType'),     selected.event_type],
                [t('details.fields.piiCategories'), selected.pii_categories?.join(', ') || '—'],
                [t('details.fields.inputHash'),     selected.input_hash ?? '—'],
                [t('details.fields.latency'),       selected.latency_ms ? `${selected.latency_ms} ms` : '—'],
                [t('details.fields.cost'),          selected.cost_eur ? `${Number(selected.cost_eur).toFixed(6)} EUR` : '—'],
              ].map(([label, value]) => (
                <div key={label} className="flex gap-3">
                  <span className="text-mgray w-32 flex-shrink-0">{label}:</span>
                  <span className="text-white break-all">{value}</span>
                </div>
              ))}
              {selected.block_reason && (
                <div className={`mt-3 rounded-lg px-3 py-2 text-xs border ${
                  selected.policy_result === 'error'
                    ? 'bg-purple-900/20 border-purple-700/50 text-purple-300'
                    : 'bg-red-900/20 border-red-700/50 text-red-300'
                }`}>
                  {selected.policy_result === 'error' ? t('details.errorDetails') : t('details.blockReason')}: {selected.block_reason}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
