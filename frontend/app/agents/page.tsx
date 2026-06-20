'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { api, Agent, AgentStatus, RiskLevel } from '@/lib/api';
import RiskBadge from '@/components/RiskBadge';

const STATUS_STYLE: Record<AgentStatus, string> = {
  active:      'text-green-400',
  suspended:   'text-yellow-400',
  quarantined: 'text-red-400',
  retired:     'text-mgray/50',
};

const RISK_OPTS: { value: RiskLevel | ''; label: string }[] = [
  { value: '', label: 'Wszystkie' },
  { value: 'minimal', label: 'Minimalne' },
  { value: 'limited', label: 'Ograniczone' },
  { value: 'high', label: 'Wysokie' },
  { value: 'unacceptable', label: 'Niedopuszczalne' },
];

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterRisk, setFilterRisk] = useState<RiskLevel | ''>('');
  const [filterStatus, setFilterStatus] = useState<AgentStatus | ''>('');
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(() => {
    const params: Record<string, string> = {};
    if (filterRisk)   params.risk_level = filterRisk;
    if (filterStatus) params.status = filterStatus;
    api.agents.list(params)
      .then(setAgents)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [filterRisk, filterStatus]);

  useEffect(() => { load(); }, [load]);

  async function changeStatus(id: string, status: AgentStatus) {
    await api.agents.updateStatus(id, status);
    load();
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Rejestr Agentów</h1>
          <p className="text-mgray text-sm mt-0.5">{agents.length} agentów</p>
        </div>
        <button
          onClick={() => setShowForm(true)}
          className="px-4 py-2 bg-teal text-dark text-sm font-semibold rounded-lg hover:bg-teal/90 transition-colors"
        >
          + Zarejestruj agenta
        </button>
      </div>

      {/* Filtry */}
      <div className="flex gap-3">
        <select
          value={filterRisk}
          onChange={e => setFilterRisk(e.target.value as RiskLevel | '')}
          className="bg-navy border border-blue/40 text-sm text-white rounded-lg px-3 py-2 focus:outline-none focus:border-teal"
        >
          {RISK_OPTS.map(o => <option key={o.value} value={o.value}>{o.label} ryzyko</option>)}
        </select>
        <select
          value={filterStatus}
          onChange={e => setFilterStatus(e.target.value as AgentStatus | '')}
          className="bg-navy border border-blue/40 text-sm text-white rounded-lg px-3 py-2 focus:outline-none focus:border-teal"
        >
          <option value="">Wszystkie statusy</option>
          <option value="active">Aktywny</option>
          <option value="suspended">Zawieszony</option>
          <option value="quarantined">Kwarantanna</option>
          <option value="retired">Wycofany</option>
        </select>
      </div>

      {/* Tabela */}
      <div className="bg-navy rounded-lg border border-blue/30 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-blue/30">
              {['Nazwa', 'Ryzyko', 'Status', 'Właściciel', 'Model', 'Nadzór', 'Akcje'].map(h => (
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
            {!loading && agents.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-mgray/50">Brak agentów</td></tr>
            )}
            {agents.map(a => (
              <tr key={a.id} className="hover:bg-blue/10 transition-colors">
                <td className="px-4 py-3">
                  <Link href={`/agents/${a.id}`} className="text-white font-medium hover:text-teal transition-colors">
                    {a.name}
                  </Link>
                  {a.annex_iii_cat && (
                    <div className="text-xs text-mgray/60 mt-0.5">Aneks III: {a.annex_iii_cat}</div>
                  )}
                </td>
                <td className="px-4 py-3"><RiskBadge level={a.risk_level} /></td>
                <td className="px-4 py-3">
                  <span className={`text-xs font-semibold ${STATUS_STYLE[a.status]}`}>
                    {a.status.toUpperCase()}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <div className="text-xs text-white">{a.owner_name}</div>
                  <div className="text-xs text-mgray/60">{a.team}</div>
                </td>
                <td className="px-4 py-3 text-xs text-mgray">{a.model_id.split('-').slice(0,2).join('-')}</td>
                <td className="px-4 py-3">
                  {a.requires_oversight
                    ? <span className="text-orange-400 text-xs font-semibold">● Wymagany</span>
                    : <span className="text-mgray/40 text-xs">—</span>}
                </td>
                <td className="px-4 py-3">
                  <div className="flex gap-2">
                    {a.status === 'active' && (
                      <button
                        onClick={() => changeStatus(a.id, 'suspended')}
                        className="text-xs text-yellow-400 border border-yellow-700/50 px-2 py-1 rounded hover:bg-yellow-900/30 transition-colors"
                      >
                        Zawieś
                      </button>
                    )}
                    {a.status === 'suspended' && (
                      <button
                        onClick={() => changeStatus(a.id, 'active')}
                        className="text-xs text-green-400 border border-green-700/50 px-2 py-1 rounded hover:bg-green-900/30 transition-colors"
                      >
                        Aktywuj
                      </button>
                    )}
                    <Link
                      href={`/agents/${a.id}`}
                      className="text-xs text-teal border border-teal/30 px-2 py-1 rounded hover:bg-teal/10 transition-colors"
                    >
                      Szczegóły
                    </Link>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Modal rejestracji */}
      {showForm && <RegisterModal onClose={() => setShowForm(false)} onDone={() => { setShowForm(false); load(); }} />}
    </div>
  );
}

function RegisterModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [form, setForm] = useState({
    name: '', description: '', owner_name: '', owner_email: '',
    team: '', model_id: 'claude-haiku-4-5-20251001', monthly_budget_eur: '50',
  });
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState('');

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true); setError('');
    try {
      const res = await api.agents.create({ ...form, monthly_budget_eur: parseFloat(form.monthly_budget_eur) });
      setResult(res as Record<string, unknown>);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Błąd rejestracji');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-dark border border-blue/40 rounded-xl w-full max-w-lg shadow-2xl" onClick={e => e.stopPropagation()}>
        <div className="px-6 py-4 border-b border-blue/30">
          <h2 className="text-lg font-bold text-white">Rejestracja Agenta AI</h2>
          <p className="text-xs text-mgray mt-0.5">Claude automatycznie sklasyfikuje ryzyko AI Act</p>
        </div>

        {result ? (
          <div className="px-6 py-6 space-y-4">
            <div className="bg-green-900/30 border border-green-700 rounded-lg px-4 py-3 text-green-300 text-sm">
              Agent zarejestrowany pomyślnie!
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-mgray">Poziom ryzyka:</span>
                <span className="text-white font-semibold">{String(result.risk_level).toUpperCase()}</span>
              </div>
              {result.annex_iii_cat && (
                <div className="flex justify-between">
                  <span className="text-mgray">Kategoria Aneksu III:</span>
                  <span className="text-white">{String(result.annex_iii_cat)}</span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-mgray">Nadzór wymagany:</span>
                <span className={result.requires_oversight ? 'text-orange-400 font-semibold' : 'text-green-400'}>
                  {result.requires_oversight ? 'TAK' : 'NIE'}
                </span>
              </div>
              {result.legal_basis && (
                <div className="mt-3 bg-navy rounded-lg p-3 text-xs text-mgray">{String(result.legal_basis)}</div>
              )}
            </div>
            <button onClick={onDone} className="w-full py-2.5 bg-teal text-dark font-semibold rounded-lg hover:bg-teal/90">
              Gotowe
            </button>
          </div>
        ) : (
          <form onSubmit={submit} className="px-6 py-4 space-y-4">
            {[
              { key: 'name', label: 'Nazwa agenta', placeholder: 'np. Agent Obsługi Klienta', required: true },
              { key: 'owner_name', label: 'Właściciel', placeholder: 'Jan Kowalski', required: true },
              { key: 'owner_email', label: 'Email właściciela', placeholder: 'j.kowalski@firma.pl', required: true },
              { key: 'team', label: 'Zespół', placeholder: 'np. Obsługa Klienta', required: false },
            ].map(({ key, label, placeholder, required }) => (
              <div key={key}>
                <label className="text-xs text-mgray mb-1 block">{label}</label>
                <input
                  required={required}
                  value={form[key as keyof typeof form]}
                  onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                  placeholder={placeholder}
                  className="w-full bg-navy border border-blue/40 rounded-lg px-3 py-2 text-sm text-white placeholder-mgray/50 focus:outline-none focus:border-teal"
                />
              </div>
            ))}
            <div>
              <label className="text-xs text-mgray mb-1 block">Opis agenta (używany do klasyfikacji AI Act)</label>
              <textarea
                required
                value={form.description}
                onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                placeholder="Opisz dokładnie co robi agent, jakie decyzje podejmuje, jakie dane przetwarza..."
                className="w-full bg-navy border border-blue/40 rounded-lg px-3 py-2 text-sm text-white placeholder-mgray/50 focus:outline-none focus:border-teal resize-none"
                rows={4}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-mgray mb-1 block">Model</label>
                <select
                  value={form.model_id}
                  onChange={e => setForm(f => ({ ...f, model_id: e.target.value }))}
                  className="w-full bg-navy border border-blue/40 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal"
                >
                  <option value="claude-haiku-4-5-20251001">claude-haiku-4-5</option>
                  <option value="claude-sonnet-4-6">claude-sonnet-4-6</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-mgray mb-1 block">Budżet miesięczny (EUR)</label>
                <input
                  type="number"
                  value={form.monthly_budget_eur}
                  onChange={e => setForm(f => ({ ...f, monthly_budget_eur: e.target.value }))}
                  className="w-full bg-navy border border-blue/40 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal"
                />
              </div>
            </div>
            {error && <div className="text-red-400 text-xs">{error}</div>}
            <div className="flex gap-3 pt-2">
              <button type="button" onClick={onClose} className="flex-1 py-2.5 border border-blue/40 rounded-lg text-sm text-mgray hover:bg-blue/20">
                Anuluj
              </button>
              <button type="submit" disabled={loading} className="flex-1 py-2.5 bg-teal text-dark font-semibold rounded-lg text-sm hover:bg-teal/90 disabled:opacity-50">
                {loading ? 'Klasyfikuję...' : 'Zarejestruj + Klasyfikuj'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
