'use client';

import { useEffect, useState, useCallback } from 'react';
import { api, DashboardSummary } from '@/lib/api';
import KpiCard from '@/components/KpiCard';
import LiveFeed from '@/components/LiveFeed';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, CartesianGrid,
} from 'recharts';

export default function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [timeline, setTimeline] = useState<{ hour: string; total: number; blocked: number }[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    api.dashboard.summary(7)
      .then(setSummary)
      .catch(console.error)
      .finally(() => setLoading(false));
    api.dashboard.timeline(24)
      .then(setTimeline)
      .catch(console.error);
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, [load]);

  if (loading) return <div className="text-mgray animate-pulse">Ładowanie pulpitu...</div>;
  if (!summary) return <div className="text-red-400">Błąd ładowania danych.</div>;

  const { agents, calls, pending_oversight, top_agents, recent_alerts } = summary;
  const blockRate = calls.total_calls > 0
    ? ((calls.blocked / calls.total_calls) * 100).toFixed(1)
    : '0.0';

  const chartData = top_agents.map(a => ({
    name: a.agent_name.split(' ').slice(-1)[0],
    full: a.agent_name,
    calls: a.calls,
    blocked: a.blocked,
    ok: a.calls - a.blocked,
  }));

  return (
    <div className="space-y-6">
      {/* Nagłówek */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Pulpit Operacyjny</h1>
          <p className="text-mgray text-sm mt-0.5">Ostatnie 7 dni · odświeżane co 30s</p>
        </div>
        <div className="text-xs text-mgray bg-navy px-3 py-1.5 rounded-full border border-blue/30">
          {new Date().toLocaleString('pl-PL')}
        </div>
      </div>

      {/* KPI */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          label="Aktywni agenci"
          value={agents.active}
          sub={`${agents.high_risk} wysokiego ryzyka`}
          accent="teal"
        />
        <KpiCard
          label="Wywołania (7 dni)"
          value={calls.total_calls}
          sub={`śr. latencja ${calls.avg_latency_ms ?? '—'} ms`}
          accent="green"
        />
        <KpiCard
          label="Blokady"
          value={calls.blocked}
          sub={`${blockRate}% wszystkich wywołań`}
          accent="red"
        />
        <KpiCard
          label="Oczekuje nadzoru"
          value={pending_oversight}
          sub="wymaga decyzji recenzenta"
          accent={pending_oversight > 0 ? 'orange' : 'green'}
        />
      </div>

      {/* Główna siatka */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Wykres top agentów */}
        <div className="lg:col-span-2 bg-navy rounded-lg border border-blue/30 p-4">
          <div className="text-sm font-semibold text-white mb-4">Wywołania wg agenta</div>
          {chartData.length === 0 ? (
            <div className="text-mgray/50 text-sm text-center py-10">Brak danych</div>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={chartData} barGap={4}>
                <XAxis dataKey="name" tick={{ fill: '#CBD5E1', fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: '#CBD5E1', fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip
                  contentStyle={{ background: '#0D1B2A', border: '1px solid #1E6FBF', borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: '#CBD5E1' }}
                  formatter={(v, name) => [v, name === 'ok' ? 'Dozwolone' : 'Zablokowane']}
                  labelFormatter={(_, payload) => payload?.[0]?.payload?.full ?? ''}
                />
                <Bar dataKey="ok" stackId="a" fill="#2D9C61" radius={[0, 0, 4, 4]} name="ok" />
                <Bar dataKey="blocked" stackId="a" fill="#C0392B" radius={[4, 4, 0, 0]} name="blocked" />
              </BarChart>
            </ResponsiveContainer>
          )}
          <div className="flex gap-6 mt-2 text-xs text-mgray">
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-green-600 inline-block" />Dozwolone</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-red-600 inline-block" />Zablokowane</span>
          </div>
        </div>

        {/* Live feed */}
        <div className="h-80">
          <LiveFeed />
        </div>
      </div>

      {/* Wykres timeline (24h) */}
      <div className="bg-navy rounded-lg border border-blue/30 p-4">
        <div className="flex items-center justify-between mb-4">
          <div className="text-sm font-semibold text-white">Wywołania wg godziny (ostatnie 24h)</div>
          <div className="text-xs text-mgray/60">odświeżane co 30s</div>
        </div>
        {timeline.length === 0 ? (
          <div className="text-center py-8 text-mgray/40 text-sm">Brak danych w ostatnich 24h</div>
        ) : (
          <ResponsiveContainer width="100%" height={160}>
            <LineChart data={timeline} margin={{ top: 4, right: 8, bottom: 0, left: -10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1E3A5F" vertical={false} />
              <XAxis
                dataKey="hour"
                tick={{ fill: '#CBD5E1', fontSize: 10 }}
                axisLine={false} tickLine={false}
                interval={Math.floor(timeline.length / 6)}
              />
              <YAxis tick={{ fill: '#CBD5E1', fontSize: 10 }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{ background: '#0D1B2A', border: '1px solid #1E6FBF', borderRadius: 8, fontSize: 11 }}
                labelStyle={{ color: '#CBD5E1' }}
                formatter={(v: number, name: string) => [v, name === 'total' ? 'Ogółem' : 'Zablokowane']}
              />
              <Line type="monotone" dataKey="total" stroke="#00B4D8" strokeWidth={2} dot={false} name="total" />
              <Line type="monotone" dataKey="blocked" stroke="#C0392B" strokeWidth={2} dot={false} name="blocked" />
            </LineChart>
          </ResponsiveContainer>
        )}
        <div className="flex gap-6 mt-2 text-xs text-mgray">
          <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 bg-teal inline-block rounded" />Ogółem</span>
          <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 bg-red-600 inline-block rounded" />Zablokowane</span>
        </div>
      </div>

      {/* Ostatnie alerty */}
      <div className="bg-navy rounded-lg border border-blue/30">
        <div className="px-5 py-3 border-b border-blue/30 flex items-center justify-between">
          <span className="text-sm font-semibold text-white">Ostatnie zdarzenia bezpieczeństwa</span>
          <a href="/audit" className="text-xs text-teal hover:underline">Zobacz dziennik →</a>
        </div>
        <div className="divide-y divide-blue/20">
          {recent_alerts.length === 0 && (
            <div className="px-5 py-6 text-center text-mgray/50 text-sm">Brak alertów w tym okresie</div>
          )}
          {recent_alerts.map((a, i) => (
            <div key={i} className="px-5 py-3 flex items-center gap-4 hover:bg-blue/10">
              <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                a.policy_result === 'blocked' ? 'bg-red-500' : 'bg-orange-400'
              }`} />
              <div className="flex-1 min-w-0">
                <div className="text-sm text-white font-medium">{a.agent_name}</div>
                <div className="text-xs text-mgray truncate">{a.block_reason ?? a.event_type}</div>
              </div>
              <div className="text-xs text-mgray flex-shrink-0">
                {new Date(a.time).toLocaleTimeString('pl-PL')}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Koszty i statystyki API */}
      <div className="grid grid-cols-3 gap-4 text-xs">
        {/* Koszt — z tooltipem rozbicia na agentów */}
        <div className="relative group bg-navy rounded-lg border border-blue/30 px-4 py-3 cursor-default">
          <div className="text-mgray/70 mb-1">Łączny koszt (7 dni)</div>
          <div className="text-white font-semibold text-base">
            {(calls.total_cost_eur ?? 0).toFixed(4)} EUR
          </div>
          {/* Tooltip */}
          <div className="absolute bottom-full left-0 mb-2 w-64 bg-dark border border-blue/40 rounded-lg shadow-xl
                          opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity duration-150 z-10">
            <div className="px-3 py-2 border-b border-blue/20 text-mgray/60 text-xs font-semibold uppercase tracking-wide">
              Koszt wg agenta (7 dni)
            </div>
            <div className="px-3 py-2 space-y-2">
              {top_agents.length === 0 ? (
                <div className="text-mgray/50">Brak danych</div>
              ) : (
                [...top_agents]
                  .sort((a, b) => (b.cost_eur ?? 0) - (a.cost_eur ?? 0))
                  .map(a => {
                    const total = calls.total_cost_eur ?? 0;
                    const pct = total > 0 ? ((a.cost_eur ?? 0) / total) * 100 : 0;
                    return (
                      <div key={a.agent_name}>
                        <div className="flex justify-between text-xs mb-0.5">
                          <span className="text-lgray truncate max-w-[140px]" title={a.agent_name}>
                            {a.agent_name.split(' ').slice(0, 3).join(' ')}
                          </span>
                          <span className="text-white font-mono ml-2 flex-shrink-0">
                            {(a.cost_eur ?? 0).toFixed(4)} EUR
                          </span>
                        </div>
                        <div className="w-full bg-blue/20 rounded-full h-1">
                          <div
                            className="bg-teal h-1 rounded-full"
                            style={{ width: `${pct.toFixed(1)}%` }}
                          />
                        </div>
                      </div>
                    );
                  })
              )}
            </div>
            <div className="px-3 py-1.5 border-t border-blue/20 text-mgray/40 text-xs">
              tylko koszt tokenów Anthropic
            </div>
          </div>
        </div>

        {/* Wykrycia PII */}
        <div className="bg-navy rounded-lg border border-blue/30 px-4 py-3">
          <div className="text-mgray/70 mb-1">Wykrycia PII</div>
          <div className="text-white font-semibold text-base">{calls.pii_calls}</div>
        </div>

        {/* Do nadzoru */}
        <div className="bg-navy rounded-lg border border-blue/30 px-4 py-3">
          <div className="text-mgray/70 mb-1">Do nadzoru</div>
          <div className="text-white font-semibold text-base">{calls.oversight_required}</div>
        </div>
      </div>
    </div>
  );
}
