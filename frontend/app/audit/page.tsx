'use client';

import { useCallback, useEffect, useState } from 'react';
import { api, AuditEntry } from '@/lib/api';
import PolicyBadge from '@/components/PolicyBadge';

export default function AuditPage() {
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
          <h1 className="text-2xl font-bold text-white">Dziennik Audytowy</h1>
          <p className="text-mgray text-sm mt-0.5">
            Niezmienialny zapis wszystkich wywołań agentów AI
          </p>
        </div>
        <div className="text-sm text-mgray bg-navy px-3 py-1.5 rounded-full border border-blue/30">
          {entries.length} wpisów
        </div>
      </div>

      {/* Filtry */}
      <div className="flex gap-3 flex-wrap">
        <select
          value={filterResult}
          onChange={e => setFilterResult(e.target.value)}
          className="bg-navy border border-blue/40 text-sm text-white rounded-lg px-3 py-2 focus:outline-none focus:border-teal"
        >
          <option value="">Wszystkie wyniki</option>
          <option value="allowed">Dozwolone</option>
          <option value="blocked">Zablokowane</option>
          <option value="oversight_required">Do nadzoru</option>
          <option value="error">Błąd</option>
        </select>
        <select
          value={filterPii}
          onChange={e => setFilterPii(e.target.value)}
          className="bg-navy border border-blue/40 text-sm text-white rounded-lg px-3 py-2 focus:outline-none focus:border-teal"
        >
          <option value="">Wszystkie (PII)</option>
          <option value="true">Z wykrytym PII</option>
          <option value="false">Bez PII</option>
        </select>
        <select
          value={filterDays}
          onChange={e => setFilterDays(e.target.value)}
          className="bg-navy border border-blue/40 text-sm text-white rounded-lg px-3 py-2 focus:outline-none focus:border-teal"
        >
          <option value="1">Ostatni dzień</option>
          <option value="7">Ostatnie 7 dni</option>
          <option value="30">Ostatnie 30 dni</option>
        </select>
      </div>

      {/* Tabela */}
      <div className="bg-navy rounded-lg border border-blue/30 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-blue/30">
              {['Czas', 'Agent', 'Wynik', 'Typ zdarzenia', 'PII', 'Latencja', 'Szczegóły'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs uppercase tracking-wider text-mgray font-semibold">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-blue/20">
            {loading && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-mgray animate-pulse">Ładowanie...</td></tr>
            )}
            {!loading && entries.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-mgray/50">Brak wpisów w tym okresie</td></tr>
            )}
            {entries.map((e, i) => (
              <tr key={i} className={`hover:bg-blue/10 transition-colors ${
                e.policy_result === 'blocked' ? 'bg-red-900/10' :
                e.policy_result === 'oversight_required' ? 'bg-orange-900/10' :
                e.policy_result === 'error' ? 'bg-purple-900/10' : ''
              }`}>
                <td className="px-4 py-2.5">
                  <div className="text-xs text-white font-mono">
                    {new Date(e.time).toLocaleTimeString('pl-PL')}
                  </div>
                  <div className="text-xs text-mgray/60">
                    {new Date(e.time).toLocaleDateString('pl-PL')}
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
                    <span className="text-xs text-yellow-400 font-semibold">{e.pii_count} encji</span>
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
                    Pokaż
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
              <h2 className="text-base font-bold text-white">Szczegóły wywołania</h2>
              <button onClick={() => setSelected(null)} className="text-mgray hover:text-white text-xl">×</button>
            </div>
            <div className="px-6 py-5 space-y-3 text-sm">
              {[
                ['Agent',        selected.agent_name],
                ['Call ID',      selected.call_id],
                ['Task ID',      selected.task_id],
                ['Wynik',        selected.policy_result],
                ['Typ zdarzenia',selected.event_type],
                ['PII kategorie',selected.pii_categories?.join(', ') || '—'],
                ['Skrót wejścia',selected.input_hash ?? '—'],
                ['Latencja',     selected.latency_ms ? `${selected.latency_ms} ms` : '—'],
                ['Koszt',        selected.cost_eur ? `${Number(selected.cost_eur).toFixed(6)} EUR` : '—'],
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
                  {selected.policy_result === 'error' ? 'Szczegóły błędu' : 'Powód blokady'}: {selected.block_reason}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
