'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { authHeaders, handle401 } from '@/lib/api';

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

interface RequirementAssessment {
  article: string; title: string; description: string;
  status: 'yes' | 'no' | 'partial' | 'na' | 'undeclared';
  severity: 'critical' | 'major' | 'minor';
  deadline_days: number;
  source: 'auto' | 'declared' | 'undeclared';
  notes: string;
}

interface ReportData {
  agent: {
    id: string; name: string; description: string;
    owner_name: string; owner_email: string; team: string;
    risk_level: string; annex_iii_cat: string | null; legal_basis: string | null;
    requires_oversight: boolean; status: string; model_id: string;
    monthly_budget_eur: number;
  };
  stats: {
    total_calls: number; blocked: number; oversight: number;
    pii_calls: number; avg_latency: number | null; total_cost: number;
  };
  narrative: string;
  generated_at: string;
  compliance_status: string;
  requirements: RequirementAssessment[];
}

const RISK_STYLE: Record<string, string> = {
  minimal:      'bg-green-900/30 text-green-300 border-green-700',
  limited:      'bg-blue-900/30 text-blue-300 border-blue-700',
  high:         'bg-orange-900/30 text-orange-300 border-orange-700',
  unacceptable: 'bg-red-900/30 text-red-300 border-red-700',
};

const RISK_LABEL: Record<string, string> = {
  minimal: 'Minimalne', limited: 'Ograniczone',
  high: 'Wysokie', unacceptable: 'Niedopuszczalne',
};

// Tłumaczenie enuma severity (z ai_act_requirements.default_severity, przez
// backend) na etykietę/kolor PL — czysta prezentacja, nie treść compliance.
const SEV_LABEL: Record<string, string> = { critical: 'Krytyczna', major: 'Poważna', minor: 'Drobna' };
const SEV_COLOR: Record<string, string> = {
  critical: 'text-red-400', major: 'text-orange-400', minor: 'text-yellow-400',
};
const STATUS_LABEL: Record<string, string> = {
  yes: 'Spełnione', partial: 'Częściowo', no: 'Luka', na: 'Nie dotyczy', undeclared: 'Nie ocenione',
};

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const [report, setReport] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    authHeaders()
      .then(headers => fetch(`${API}/agents/${id}/report`, { cache: 'no-store', headers }))
      .then(r => {
        if (r.status === 401) { handle401(); throw new Error('Sesja wygasła'); }
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json();
      })
      .then(setReport)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  async function downloadPdf() {
    setGenerating(true);
    try {
      const r = await fetch(`${API}/agents/${id}/report/pdf`, { headers: await authHeaders() });
      if (r.status === 401) { handle401(); throw new Error('Sesja wygasła'); }
      if (!r.ok) throw new Error(`${r.status}`);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `ai-act-raport-${id.slice(0, 8)}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error(e);
    } finally {
      setGenerating(false);
    }
  }

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-4">
        <div className="w-10 h-10 border-4 border-teal border-t-transparent rounded-full animate-spin" />
        <div className="text-mgray text-sm">Generowanie raportu zgodności z AI Act...</div>
      </div>
    );
  }

  if (error || !report) {
    return (
      <div className="text-center py-20">
        <div className="text-red-400 mb-4">Błąd generowania raportu: {error}</div>
        <Link href={`/agents/${id}`} className="text-teal hover:underline text-sm">← Powrót do agenta</Link>
      </div>
    );
  }

  const { agent, stats, narrative, generated_at, requirements } = report;
  const risk = agent.risk_level;
  const gaps = requirements.filter(r => r.status === 'no' || r.status === 'partial' || r.status === 'undeclared');
  const blockRate = stats.total_calls > 0
    ? ((stats.blocked / stats.total_calls) * 100).toFixed(1)
    : '0.0';

  return (
    <div className="space-y-5 max-w-4xl print:max-w-none print:space-y-4">
      {/* Toolbar (ukrywany przy druku) */}
      <div className="flex items-center justify-between print:hidden">
        <div className="flex items-center gap-2 text-sm text-mgray">
          <Link href="/agents" className="hover:text-teal">Agenci</Link>
          <span>/</span>
          <Link href={`/agents/${id}`} className="hover:text-teal">{agent.name}</Link>
          <span>/</span>
          <span className="text-white">Raport AI Act</span>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => window.print()}
            className="px-4 py-2 text-sm border border-blue/40 rounded-lg text-mgray hover:bg-blue/20 transition-colors"
          >
            Drukuj
          </button>
          <button
            onClick={downloadPdf}
            disabled={generating}
            className="px-4 py-2 text-sm bg-teal text-dark font-semibold rounded-lg hover:bg-teal/90 disabled:opacity-50 transition-colors"
          >
            {generating ? (
              <span className="flex items-center gap-2">
                <span className="w-3 h-3 border-2 border-dark border-t-transparent rounded-full animate-spin" />
                Generuję PDF...
              </span>
            ) : 'Pobierz PDF'}
          </button>
        </div>
      </div>

      {/* Nagłówek raportu */}
      <div className="bg-navy border border-blue/30 rounded-xl p-6 print:border print:rounded-none">
        <div className="text-xs text-teal font-semibold uppercase tracking-wider mb-1">
          GovAI · Raport Zgodności EU AI Act · Rozporządzenie (UE) 2024/1689
        </div>
        <h1 className="text-2xl font-bold text-white mt-2 mb-3">{agent.name}</h1>
        <div className="flex items-center gap-3 flex-wrap">
          <span className={`px-3 py-1 rounded-lg border text-sm font-semibold ${RISK_STYLE[risk] ?? RISK_STYLE.minimal}`}>
            Ryzyko: {RISK_LABEL[risk] ?? risk}
          </span>
          {agent.annex_iii_cat && (
            <span className="text-xs text-mgray border border-blue/30 px-2 py-1 rounded">
              Aneks III: {agent.annex_iii_cat}
            </span>
          )}
          {agent.requires_oversight && (
            <span className="text-xs text-orange-400 border border-orange-700/50 px-2 py-1 rounded">
              ◎ Nadzór wymagany
            </span>
          )}
        </div>
        <div className="mt-4 pt-4 border-t border-blue/20 flex gap-8 text-xs text-mgray">
          <div><span className="text-mgray/60">Właściciel: </span>{agent.owner_name}</div>
          <div><span className="text-mgray/60">Zespół: </span>{agent.team || '—'}</div>
          <div><span className="text-mgray/60">Model: </span>{agent.model_id}</div>
          <div><span className="text-mgray/60">Wygenerowano: </span>{new Date(generated_at).toLocaleString('pl-PL')}</div>
        </div>
      </div>

      {/* 1. Streszczenie */}
      <div className="bg-navy border border-blue/30 rounded-xl p-6">
        <h2 className="text-sm font-bold text-white uppercase tracking-wider mb-1">1. Streszczenie Wykonawcze</h2>
        <div className="w-8 h-0.5 bg-teal mb-4" />
        <p className="text-sm text-mgray leading-relaxed">{narrative}</p>
      </div>

      {/* 2. Profil */}
      <div className="bg-navy border border-blue/30 rounded-xl p-6">
        <h2 className="text-sm font-bold text-white uppercase tracking-wider mb-1">2. Profil Systemu AI</h2>
        <div className="w-8 h-0.5 bg-teal mb-4" />
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
          {([
            ['Model AI',          agent.model_id],
            ['Status',            agent.status.toUpperCase()],
            ['Kategoria An. III', agent.annex_iii_cat || 'Brak'],
            ['Nadzór człowieka',  agent.requires_oversight ? 'WYMAGANY' : 'Nie wymagany'],
            ['Email właściciela', agent.owner_email],
            ['Budżet / mies.',    `${agent.monthly_budget_eur} EUR`],
          ] as [string, string][]).map(([label, value]) => (
            <div key={label}>
              <div className="text-mgray/60 text-xs mb-0.5">{label}</div>
              <div className="text-white font-medium text-sm">{value}</div>
            </div>
          ))}
        </div>
        {agent.legal_basis && (
          <div className="mt-4 pt-4 border-t border-blue/20">
            <div className="text-xs text-mgray/60 mb-1">Podstawa prawna i klasyfikacja</div>
            <p className="text-sm text-mgray leading-relaxed">{agent.legal_basis}</p>
          </div>
        )}
      </div>

      {/* 3. Statystyki */}
      <div className="bg-navy border border-blue/30 rounded-xl p-6">
        <h2 className="text-sm font-bold text-white uppercase tracking-wider mb-1">3. Statystyki Operacyjne (30 dni)</h2>
        <div className="w-8 h-0.5 bg-teal mb-4" />
        <div className="grid grid-cols-3 gap-3">
          {[
            { label: 'Wywołania',     value: stats.total_calls,                                          color: 'text-teal' },
            { label: 'Blokady',       value: `${stats.blocked} (${blockRate}%)`,                        color: 'text-red-400' },
            { label: 'Do nadzoru',    value: stats.oversight,                                            color: 'text-orange-400' },
            { label: 'Z PII',         value: stats.pii_calls,                                           color: 'text-yellow-400' },
            { label: 'Śr. latencja',  value: stats.avg_latency ? `${Math.round(stats.avg_latency)} ms` : '—', color: 'text-white' },
            { label: 'Koszt API',     value: `${(stats.total_cost || 0).toFixed(4)} EUR`,              color: 'text-white' },
          ].map(({ label, value, color }) => (
            <div key={label} className="bg-dark/50 rounded-lg px-4 py-3">
              <div className="text-xs text-mgray/60 mb-1">{label}</div>
              <div className={`text-xl font-bold ${color}`}>{value}</div>
            </div>
          ))}
        </div>
      </div>

      {/* 4. Luki compliance */}
      <div className="bg-navy border border-blue/30 rounded-xl p-6">
        <h2 className="text-sm font-bold text-white uppercase tracking-wider mb-1">4. Ocena Zgodności z EU AI Act</h2>
        <div className="w-8 h-0.5 bg-teal mb-4" />
        {gaps.length === 0 ? (
          <p className="text-sm text-green-400">
            Brak zidentyfikowanych luk — wymagania potwierdzone jako spełnione lub nie dotyczące
            w deklaracjach zgodności (zakładka Rejestr).
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-blue/30">
                {['Artykuł', 'Wymaganie', 'Waga', 'Termin'].map(h => (
                  <th key={h} className="pb-3 text-left text-xs text-mgray/60 uppercase tracking-wider font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-blue/20">
              {gaps.map((g, i) => (
                <tr key={i}>
                  <td className="py-2.5 font-mono text-xs text-teal font-semibold">{g.article}</td>
                  <td className="py-2.5 text-white">
                    {g.title}
                    <span className="ml-2 text-[10px] text-mgray/50">({STATUS_LABEL[g.status] ?? g.status})</span>
                  </td>
                  <td className={`py-2.5 text-xs font-semibold ${SEV_COLOR[g.severity] ?? 'text-mgray'}`}>
                    {SEV_LABEL[g.severity] ?? g.severity}
                  </td>
                  <td className="py-2.5 text-mgray text-xs">
                    {g.deadline_days === 0 ? 'NATYCHMIAST' : `${g.deadline_days} dni`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Stopka */}
      <div className="text-center py-3 text-xs text-mgray/40 border-t border-blue/20">
        Raport wygenerowany przez GovAI v0.2.0 · EU AI Act (Rozporządzenie UE 2024/1689) ·
        Dokument ma charakter informacyjny. Nie stanowi porady prawnej.
      </div>
    </div>
  );
}
