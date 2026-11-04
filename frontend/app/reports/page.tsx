'use client';

import { useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { authHeaders, handle401 } from '@/lib/api';
import { useFormat } from '@/lib/format';

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

const RISK_COLOR: Record<string, string> = {
  minimal: 'text-green-400', limited: 'text-blue-400',
  high: 'text-orange-400', unacceptable: 'text-red-400',
};
const RISK_BG: Record<string, string> = {
  minimal: 'bg-green-900/20 border-green-700',
  limited: 'bg-blue-900/20 border-blue-700',
  high: 'bg-orange-900/20 border-orange-700',
  unacceptable: 'bg-red-900/20 border-red-700',
};

interface Summary {
  period_days: number;
  generated_at: string;
  kpi: Record<string, number | null>;
  risk_dist: Record<string, number>;
  agents_count: number;
  budget_alerts: { name: string; actual: number; threshold: number; pct: number }[];
  overdue_reviews: { name: string; next_review_date: string }[];
  oversight_hist: Record<string, number | null>;
  top_agents: { agent_name: string; calls: number; blocked: number; cost_eur: number }[];
  pii_cats: { cat: string; cnt: number }[];
  policy_hits: { policy_id: string; cnt: number }[];
}

export default function ReportsPage() {
  const t = useTranslations('reports');
  const tc = useTranslations('common');
  const fmt = useFormat();
  const [days, setDays] = useState(30);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchSummary();
  }, [days]);

  async function fetchSummary() {
    setLoading(true);
    setError('');
    try {
      const r = await fetch(`${API}/reports/enterprise?days=${days}`, {
        cache: 'no-store',
        headers: await authHeaders(),
      });
      if (r.status === 401) { handle401(); throw new Error(t('sessionExpired')); }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setSummary(await r.json());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function downloadPdf() {
    setGenerating(true);
    try {
      const r = await fetch(`${API}/reports/enterprise/pdf?days=${days}`, {
        headers: await authHeaders(),
      });
      if (r.status === 401) { handle401(); throw new Error(t('sessionExpired')); }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href = url;
      a.download = `govai-raport-enterprise-${new Date().toISOString().slice(0,10)}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      alert(t('pdfError', { error: String(e) }));
    } finally {
      setGenerating(false);
    }
  }

  const kpi = summary?.kpi ?? {};
  const total   = Number(kpi.total_calls ?? 0);
  const blocked = Number(kpi.blocked ?? 0);
  const pii     = Number(kpi.pii_calls ?? 0);
  const cost    = Number(kpi.total_cost ?? 0);

  return (
    <div className="space-y-6 max-w-5xl">
      {/* Nagłówek */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">{t('header.title')}</h1>
          <p className="text-mgray text-sm mt-1">{t('header.subtitle')}</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-sm text-mgray">
            <span>{t('period')}</span>
            {[7, 30, 90].map(d => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                  days === d ? 'bg-teal text-dark' : 'bg-navy border border-blue/30 text-mgray hover:text-white'
                }`}
              >
                {t('days', { days: d })}
              </button>
            ))}
          </div>
          <button
            onClick={downloadPdf}
            disabled={generating || loading}
            className="px-5 py-2 bg-teal text-dark font-semibold rounded-lg hover:bg-teal/90 disabled:opacity-50 transition-colors flex items-center gap-2"
          >
            {generating ? (
              <><span className="animate-spin inline-block w-4 h-4 border-2 border-dark/30 border-t-dark rounded-full" /> {t('generating')}</>
            ) : (
              t('download')
            )}
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-900/20 border border-red-700 rounded-lg px-4 py-3 text-sm text-red-300">
          {t('error', { error })}
        </div>
      )}

      {loading && (
        <div className="text-mgray text-sm animate-pulse">{t('loading')}</div>
      )}

      {summary && (
        <>
          {/* Alerty */}
          {(summary.budget_alerts.length > 0 || summary.overdue_reviews.length > 0) && (
            <div className="bg-yellow-900/20 border border-yellow-600 rounded-xl p-4 space-y-1.5">
              <div className="text-xs font-semibold text-yellow-400 mb-2">{t('alerts.title')}</div>
              {summary.budget_alerts.map((a, i) => (
                <div key={i} className="text-sm text-yellow-200">
                  {t.rich('alerts.budgetExceeded', {
                    name: a.name,
                    actual: a.actual.toFixed(2),
                    pct: String(a.pct),
                    threshold: a.threshold.toFixed(0),
                    b: (c) => <span className="font-semibold">{c}</span>,
                  })}
                </div>
              ))}
              {summary.overdue_reviews.map((o, i) => (
                <div key={i} className="text-sm text-yellow-200">
                  {t.rich('alerts.overdueReview', {
                    name: o.name,
                    date: o.next_review_date?.slice(0, 10) ?? '—',
                    b: (c) => <span className="font-semibold">{c}</span>,
                  })}
                </div>
              ))}
            </div>
          )}

          {/* KPI kafelki */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {[
              { label: t('kpi.agents'), value: summary.agents_count, sub: t('kpi.agentsSub'), color: 'text-teal' },
              { label: t('kpi.calls'), value: fmt.number(total), sub: t('days', { days }), color: 'text-white' },
              { label: t('kpi.blocked'), value: blocked, sub: `${(blocked/Math.max(total,1)*100).toFixed(1)}%`, color: 'text-red-400' },
              { label: t('kpi.pii'), value: pii, sub: t('kpi.piiSub'), color: 'text-yellow-400' },
              { label: t('kpi.cost'), value: `${cost.toFixed(2)} EUR`, sub: t('kpi.costSub'), color: 'text-orange-400' },
            ].map(({ label, value, sub, color }) => (
              <div key={label} className="bg-navy border border-blue/30 rounded-xl p-4">
                <div className="text-xs text-mgray mb-1">{label}</div>
                <div className={`text-2xl font-bold ${color}`}>{value}</div>
                <div className="text-xs text-mgray/60 mt-0.5">{sub}</div>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-6">
            {/* Rozkład ryzyka */}
            <div className="bg-navy border border-blue/30 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-white mb-4">{t('riskDistribution')}</h3>
              <div className="space-y-3">
                {(['unacceptable','high','limited','minimal'] as const).map(rl => {
                  const cnt = summary.risk_dist[rl] ?? 0;
                  if (cnt === 0) return null;
                  const total_a = Object.values(summary.risk_dist).reduce((s,v)=>s+v,0);
                  const pct = Math.round(cnt / Math.max(total_a,1) * 100);
                  return (
                    <div key={rl}>
                      <div className="flex items-center justify-between mb-1">
                        <span className={`text-sm font-medium ${RISK_COLOR[rl]}`}>{tc(`risk.${rl}`)}</span>
                        <span className="text-sm text-white font-bold">{cnt} <span className="text-mgray font-normal">({pct}%)</span></span>
                      </div>
                      <div className="h-2 bg-dark rounded-full overflow-hidden">
                        <div
                          className="h-2 rounded-full transition-all"
                          style={{
                            width: `${pct}%`,
                            backgroundColor: { minimal:'#2D9C61', limited:'#1E6FBF', high:'#E67E22', unacceptable:'#C0392B' }[rl],
                          }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Kolejka nadzoru */}
            <div className="bg-navy border border-blue/30 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-white mb-4">{t('oversight.title')}</h3>
              <div className="space-y-2">
                {[
                  { label: t('oversight.total'), value: summary.oversight_hist.total ?? 0, color: 'text-white' },
                  { label: tc('oversightStatus.approved'), value: summary.oversight_hist.approved ?? 0, color: 'text-green-400' },
                  { label: tc('oversightStatus.rejected'), value: summary.oversight_hist.rejected ?? 0, color: 'text-red-400' },
                  { label: tc('oversightStatus.escalated'), value: summary.oversight_hist.escalated ?? 0, color: 'text-orange-400' },
                  { label: tc('oversightStatus.pending'), value: summary.oversight_hist.pending ?? 0, color: 'text-yellow-400' },
                ].map(({ label, value, color }) => (
                  <div key={label} className="flex justify-between items-center py-1 border-b border-blue/10 last:border-0">
                    <span className="text-sm text-mgray">{label}</span>
                    <span className={`text-sm font-bold ${color}`}>{Number(value)}</span>
                  </div>
                ))}
                {summary.oversight_hist.avg_review_min && (
                  <div className="text-xs text-mgray/60 pt-1">
                    {t('oversight.avgReview', { minutes: Number(summary.oversight_hist.avg_review_min).toFixed(1) })}
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-6">
            {/* Top agenci */}
            <div className="bg-navy border border-blue/30 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-white mb-4">{t('topAgents.title')}</h3>
              <div className="space-y-2">
                {summary.top_agents.map((a, i) => (
                  <div key={i} className="flex items-center justify-between py-1 border-b border-blue/10 last:border-0">
                    <div className="min-w-0">
                      <div className="text-sm text-white truncate">{a.agent_name}</div>
                      <div className="text-xs text-mgray">{t('topAgents.blockedCost', { blocked: String(a.blocked), cost: Number(a.cost_eur).toFixed(4) })}</div>
                    </div>
                    <span className="text-sm font-bold text-teal ml-2">{fmt.number(Number(a.calls))}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* PII + polityki */}
            <div className="space-y-4">
              {summary.pii_cats.length > 0 && (
                <div className="bg-navy border border-blue/30 rounded-xl p-5">
                  <h3 className="text-sm font-semibold text-white mb-3">{t('piiCategories')}</h3>
                  <div className="space-y-1.5">
                    {summary.pii_cats.slice(0, 6).map((c, i) => (
                      <div key={i} className="flex justify-between items-center text-sm">
                        <span className="text-mgray font-mono text-xs">{c.cat}</span>
                        <span className="text-yellow-400 font-bold">{c.cnt}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {summary.policy_hits.length > 0 && (
                <div className="bg-navy border border-blue/30 rounded-xl p-5">
                  <h3 className="text-sm font-semibold text-white mb-3">{t('policyHits')}</h3>
                  <div className="space-y-1.5">
                    {summary.policy_hits.map((p, i) => (
                      <div key={i} className="flex justify-between items-center text-sm">
                        <span className="text-mgray font-mono text-xs">{p.policy_id}</span>
                        <span className="text-red-400 font-bold">{p.cnt}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          <p className="text-xs text-mgray/50 text-right">
            {t('dataFrom', { date: fmt.dateTime(summary.generated_at) })}{' '}
            <button onClick={fetchSummary} className="underline hover:text-mgray">{t('refresh')}</button>
          </p>
        </>
      )}
    </div>
  );
}
