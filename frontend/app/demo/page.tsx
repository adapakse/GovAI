'use client';

import { useEffect, useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import PolicyBadge from '@/components/PolicyBadge';
import SearchBox from '@/components/SearchBox';
import { api, Agent, Provider, PolicyResult } from '@/lib/api';
import { matchesQuery, providerFieldsForModel } from '@/lib/search';
import { ensureFreshToken } from '@/lib/auth';

const GW_URL  = process.env.NEXT_PUBLIC_GATEWAY_URL ?? 'http://localhost:8001';

const RISK_STYLE: Record<string, string> = {
  minimal:      'text-green-300 border-green-700 bg-green-900/20',
  limited:      'text-blue-300 border-blue-700 bg-blue-900/20',
  high:         'text-orange-300 border-orange-700 bg-orange-900/20',
  unacceptable: 'text-red-300 border-red-700 bg-red-900/20',
};
// Etykiety oczekiwanych wyników: demo.expected.<key>
const EXPECTED_COLOR: Record<string, string> = {
  allowed:            'text-green-400',
  allowed_with_pii:   'text-yellow-400',
  blocked:            'text-red-400',
  oversight_required: 'text-orange-400',
};

// Tytuły i opisy kroków: demo.playbook.steps.<step>.title/desc
const PLAYBOOK_STEPS = [
  { step: '1', link: null,         color: 'border-teal/40 bg-teal/5' },
  { step: '2', link: '/dashboard', color: 'border-blue/40 bg-blue/5' },
  { step: '3', link: null,         color: 'border-green-700/40 bg-green-900/5' },
  { step: '4', link: '/audit',     color: 'border-yellow-700/40 bg-yellow-900/5' },
  { step: '5', link: '/audit',     color: 'border-red-700/40 bg-red-900/5' },
  { step: '6', link: '/oversight', color: 'border-orange-700/40 bg-orange-900/5' },
  { step: '7', link: null,         color: 'border-purple-700/40 bg-purple-900/5' },
];

interface ScenarioMeta { label: string; description: string; expected: string; }
interface SeedStatus { seeded: boolean; audit_entries: number; oversight_items: number; fleet_agents: number; }
interface RunResult {
  scenario_label: string; scenario_description: string; expected: string;
  agent_id: string; task_id: string; http_status: number;
  policy_result: string; gateway_response: Record<string, unknown>;
}
interface ChatMessage { role: 'user' | 'assistant'; content: string; }

// ── Wolny czat dla agentów bez scenariuszy ────────────────────────────────────
function FreeChat({ agent }: { agent: Agent }) {
  const t = useTranslations('demo');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [lastMeta, setLastMeta] = useState<{ status: number; policy: string } | null>(null);

  async function send() {
    const text = input.trim();
    if (!text || loading) return;
    setInput('');
    const newMessages: ChatMessage[] = [...messages, { role: 'user', content: text }];
    setMessages(newMessages);
    setLoading(true);
    setLastMeta(null);

    try {
      const token = await ensureFreshToken();
      const r = await fetch(`${GW_URL}/v1/chat/completions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept-Language': document.documentElement.lang,
          'X-Agent-ID': agent.id,
          'X-Task-ID': `chat-${Date.now()}`,
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          model: agent.model_id,
          messages: newMessages.map(m => ({ role: m.role, content: m.content })),
        }),
      });

      setLastMeta({ status: r.status, policy: r.status === 403 ? 'blocked' : 'allowed' });
      const data = await r.json();

      if (!r.ok) {
        const detail = data?.detail;
        const reason = typeof detail === 'object' ? detail?.reason : detail;
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: t('chat.blocked', { reason: reason ?? t('chat.defaultBlockReason') }),
        }]);
        setLastMeta({ status: r.status, policy: 'blocked' });
      } else if (data.status === 'awaiting_oversight') {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: t('chat.awaitingOversight', { id: String(data.oversight_id) }),
        }]);
        setLastMeta({ status: r.status, policy: 'oversight_required' });
      } else {
        const content = data.choices?.[0]?.message?.content ?? JSON.stringify(data);
        setMessages(prev => [...prev, { role: 'assistant', content }]);
        setLastMeta({ status: r.status, policy: 'allowed' });
      }
    } catch (e) {
      setMessages(prev => [...prev, {
        role: 'assistant', content: t('chat.connectionError', { error: String(e) }),
      }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="divide-y divide-blue/10">
      {/* Historia czatu */}
      <div className="px-5 py-4 min-h-[120px] max-h-80 overflow-y-auto space-y-3">
        {messages.length === 0 && (
          <p className="text-xs text-mgray/50 italic">
            {t('chat.emptyHint', { model: agent.model_id })}
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex gap-2 ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[80%] rounded-lg px-3 py-2 text-xs leading-relaxed ${
              m.role === 'user'
                ? 'bg-teal/20 border border-teal/40 text-white'
                : 'bg-dark/60 border border-blue/20 text-lgray'
            }`}>
              <pre className="whitespace-pre-wrap font-sans">{m.content}</pre>
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex gap-2">
            <div className="bg-dark/60 border border-blue/20 rounded-lg px-3 py-2">
              <span className="flex gap-1">
                {[0,1,2].map(i => (
                  <span key={i} className="w-1.5 h-1.5 bg-teal rounded-full animate-bounce"
                        style={{ animationDelay: `${i*0.15}s` }} />
                ))}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Status ostatniego wywołania */}
      {lastMeta && (
        <div className="px-5 py-2 flex items-center gap-3 bg-dark/20 text-xs">
          <PolicyBadge result={lastMeta.policy as PolicyResult} />
          <span className="text-mgray">HTTP {lastMeta.status}</span>
          <a href="/audit" className="text-teal hover:underline ml-auto">{t('links.audit')}</a>
          {lastMeta.policy === 'oversight_required' && (
            <a href="/oversight" className="text-orange-400 hover:underline">{t('links.oversight')}</a>
          )}
        </div>
      )}

      {/* Input */}
      <div className="px-5 py-4 flex gap-3">
        <input
          className="flex-1 bg-dark border border-blue/30 rounded-lg px-3 py-2 text-sm text-white placeholder:text-mgray/40 focus:outline-none focus:border-teal"
          placeholder={t('chat.placeholder')}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
          disabled={loading}
        />
        <button
          onClick={send}
          disabled={loading || !input.trim()}
          className="px-4 py-2 bg-teal text-dark text-sm font-semibold rounded-lg hover:bg-teal/90 disabled:opacity-40 transition-colors"
        >
          {t('chat.send')}
        </button>
        {messages.length > 0 && (
          <button
            onClick={() => { setMessages([]); setLastMeta(null); }}
            className="px-3 py-2 text-xs text-mgray hover:text-white border border-blue/20 rounded-lg"
          >
            {t('chat.clear')}
          </button>
        )}
      </div>
    </div>
  );
}

// ── Strona główna ─────────────────────────────────────────────────────────────
export default function DemoPage() {
  const t = useTranslations('demo');
  const tc = useTranslations('common');
  const [agents, setAgents] = useState<Agent[]>([]);
  const [scenarios, setScenarios] = useState<Record<string, Record<string, ScenarioMeta>>>({});
  const [running, setRunning] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, RunResult>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [seedStatus, setSeedStatus] = useState<SeedStatus | null>(null);
  const [seedLoading, setSeedLoading] = useState(false);
  const [seedMsg, setSeedMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);
  const [fleetLoading, setFleetLoading] = useState(false);
  const [playbookOpen, setPlaybookOpen] = useState(false);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [query, setQuery] = useState('');

  useEffect(() => {
    api.agents.list({ status: 'active' }).then(setAgents).catch(console.error);
    api.demo.scenarios().then(setScenarios).catch(console.error);
    api.providers.list().then(setProviders).catch(() => {});
    fetchSeedStatus();
  }, []);

  async function fetchSeedStatus() {
    try { setSeedStatus(await api.demo.seedStatus()); } catch {}
  }

  async function seed() {
    setSeedLoading(true); setSeedMsg(null);
    try {
      const data = await api.demo.seed();
      setSeedMsg({ type: 'ok', text: data.message ?? t('seed.seededEntries', { count: data.seeded_audit_entries ?? 0 }) });
      await fetchSeedStatus();
    } catch (e) { setSeedMsg({ type: 'err', text: String(e) }); }
    finally { setSeedLoading(false); }
  }

  async function reset() {
    if (!confirm(t('seed.resetConfirm'))) return;
    setSeedLoading(true); setSeedMsg(null);
    try {
      const data = await api.demo.reset();
      setSeedMsg({ type: 'ok', text: t('seed.resetDone', { audit: data.deleted_audit_entries, oversight: data.deleted_oversight_entries, fleet: data.deleted_fleet_agents }) });
      await fetchSeedStatus();
    } catch (e) { setSeedMsg({ type: 'err', text: String(e) }); }
    finally { setSeedLoading(false); }
  }

  async function seedFleet() {
    setFleetLoading(true); setSeedMsg(null);
    try {
      const data = await api.demo.seedFleet();
      setSeedMsg({ type: 'ok', text: data.message ?? t('fleet.seededAgents', { count: data.seeded_agents ?? 0 }) });
      await fetchSeedStatus();
      await api.agents.list({ status: 'active' }).then(setAgents).catch(() => {});
    } catch (e) { setSeedMsg({ type: 'err', text: String(e) }); }
    finally { setFleetLoading(false); }
  }

  async function run(agentId: string, scenarioKey: string) {
    const key = `${agentId}:${scenarioKey}`;
    setRunning(key);
    setErrors(e => { const n = { ...e }; delete n[key]; return n; });
    try {
      const data = await api.demo.run(agentId, scenarioKey) as unknown as RunResult;
      setResults(prev => ({ ...prev, [key]: data }));
      await fetchSeedStatus();
    } catch (err) { setErrors(e => ({ ...e, [key]: String(err) })); }
    finally { setRunning(null); }
  }

  function extractContent(result: RunResult): string {
    const gw = result.gateway_response;
    if (result.policy_result === 'blocked') {
      const detail = gw.detail as Record<string, unknown> | undefined;
      return detail?.reason as string ?? gw.reason as string ?? t('result.blockedByPolicy');
    }
    if (result.policy_result === 'oversight_required')
      return t('result.sentToOversight', { id: String(gw.oversight_id ?? '—'), message: String(gw.message ?? '') });
    if (result.policy_result === 'error') {
      const detail = gw.detail;
      if (typeof detail === 'string') return detail;
      const d = detail as Record<string, unknown> | undefined;
      return (d?.message as string) ?? JSON.stringify(gw, null, 2);
    }
    const choices = gw.choices as Array<{ message?: { content?: string } }> | undefined;
    return choices?.[0]?.message?.content ?? JSON.stringify(gw, null, 2);
  }

  // Filtr tekstowy: nazwa agenta, model, zespół, właściciel + nazwa/typ providera
  const agentMatches = useMemo(() => {
    return (a: Agent) => matchesQuery(
      [a.name, a.model_id, a.team, a.owner_name, ...providerFieldsForModel(a.model_id, providers)],
      query,
    );
  }, [query, providers]);

  // Oddziel agentów z scenariuszami od pozostałych (wolny czat)
  const scenarioAgentIds = new Set(Object.keys(scenarios));
  const scenarioAgents = agents.filter(a => scenarioAgentIds.has(a.id) && agentMatches(a));
  const chatAgents     = agents.filter(a => !scenarioAgentIds.has(a.id) && agentMatches(a));
  const shownCount     = scenarioAgents.length + chatAgents.length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">{t('title')}</h1>
        <p className="text-mgray text-sm mt-1">
          {t('subtitle')}
        </p>
      </div>

      {/* Panel danych demo */}
      <div className="bg-navy border border-blue/30 rounded-xl p-5 space-y-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h2 className="text-white font-semibold">{t('seed.title')}</h2>
            <p className="text-xs text-mgray mt-0.5">{t('seed.desc')}</p>
          </div>
          {seedStatus && (
            <div className="flex items-center gap-2">
              <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${
                seedStatus.seeded ? 'text-green-400 border-green-700 bg-green-900/20' : 'text-mgray border-mgray/30'
              }`}>
                {seedStatus.seeded ? t('seed.statusSeeded') : t('seed.statusEmpty')}
              </span>
              {seedStatus.seeded && (
                <span className="text-xs text-mgray">{t('seed.counts', { audit: seedStatus.audit_entries, oversight: seedStatus.oversight_items })}</span>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <button onClick={seed} disabled={seedLoading}
            className="px-4 py-2 bg-teal text-dark text-sm font-semibold rounded-lg hover:bg-teal/90 disabled:opacity-40">
            {seedLoading ? t('loading') : t('seed.button')}
          </button>
          <button onClick={reset} disabled={seedLoading}
            className="px-4 py-2 bg-red-900/30 border border-red-700 text-red-300 text-sm font-semibold rounded-lg hover:bg-red-900/50 disabled:opacity-40">
            {t('seed.reset')}
          </button>
          <button onClick={fetchSeedStatus} disabled={seedLoading}
            className="px-3 py-2 text-xs text-mgray hover:text-white border border-blue/20 rounded-lg">
            {t('seed.refresh')}
          </button>
        </div>
        {seedMsg && (
          <div className={`text-xs px-4 py-3 rounded-lg border ${
            seedMsg.type === 'ok' ? 'bg-green-900/20 border-green-700 text-green-300' : 'bg-red-900/20 border-red-700 text-red-300'
          }`}>{seedMsg.text}</div>
        )}

        {/* Flota demonstracyjna — skala rejestru */}
        <div className="border-t border-blue/20 pt-4 flex items-center justify-between flex-wrap gap-3">
          <div className="max-w-md">
            <h3 className="text-white font-semibold text-sm">{t('fleet.title')}</h3>
            <p className="text-xs text-mgray mt-0.5">
              {t('fleet.desc')}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {seedStatus && seedStatus.fleet_agents > 0 && (
              <span className="text-xs font-semibold px-2 py-0.5 rounded border text-orange-400 border-orange-700 bg-orange-900/20">
                {t('fleet.count', { count: seedStatus.fleet_agents })}
              </span>
            )}
            <button onClick={seedFleet} disabled={fleetLoading || seedLoading}
              className="px-4 py-2 bg-teal text-dark text-sm font-semibold rounded-lg hover:bg-teal/90 disabled:opacity-40">
              {fleetLoading ? t('loading') : t('fleet.button')}
            </button>
          </div>
        </div>
      </div>

      {/* Przewodnik */}
      <div className="bg-navy border border-blue/30 rounded-xl overflow-hidden">
        <button onClick={() => setPlaybookOpen(o => !o)}
          className="w-full px-5 py-4 flex items-center justify-between text-left hover:bg-blue/10">
          <span className="font-semibold text-white">{t('playbook.title')}</span>
          <span className="text-mgray text-sm">{playbookOpen ? t('playbook.collapse') : t('playbook.expand')}</span>
        </button>
        {playbookOpen && (
          <div className="px-5 pb-5 space-y-3 border-t border-blue/20">
            <p className="text-xs text-mgray pt-3">{t('playbook.intro')}</p>
            {PLAYBOOK_STEPS.map(s => (
              <div key={s.step} className={`border rounded-lg px-4 py-3 flex gap-4 ${s.color}`}>
                <div className="w-7 h-7 rounded-full bg-blue/30 text-white text-sm font-bold flex items-center justify-center flex-shrink-0">
                  {s.step}
                </div>
                <div>
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className="text-sm font-semibold text-white">{t(`playbook.steps.${s.step}.title`)}</span>
                    {s.link && <a href={s.link} className="text-xs text-teal hover:underline">{t('playbook.go')}</a>}
                  </div>
                  <p className="text-xs text-mgray mt-1 leading-relaxed">{t(`playbook.steps.${s.step}.desc`)}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Wyszukiwarka agentów */}
      <div className="flex items-center gap-3 flex-wrap">
        <SearchBox
          value={query}
          onChange={setQuery}
          placeholder={t('searchPlaceholder')}
          count={shownCount}
          total={agents.length}
        />
      </div>

      {shownCount === 0 && !query && (
        <div className="text-mgray/50 text-sm py-4">{t('noAgents')}</div>
      )}
      {shownCount === 0 && query && (
        <div className="text-mgray text-sm py-4">
          {t('noResults', { query })}
        </div>
      )}

      {/* Agenci ze scenariuszami */}
      {scenarioAgents.map(agent => (
        <div key={agent.id} className="bg-navy border border-blue/30 rounded-xl overflow-hidden">
          <div className="px-5 py-4 border-b border-blue/20 flex items-start gap-3">
            <div className="flex-1">
              <div className="flex items-center gap-3 flex-wrap">
                <span className="font-semibold text-white">{agent.name}</span>
                <span className={`text-xs font-semibold px-2 py-0.5 rounded border uppercase ${RISK_STYLE[agent.risk_level]}`}>
                  {tc(`risk.${agent.risk_level}`)}
                </span>
                <span className="text-xs text-mgray/50 font-mono">{agent.id.slice(0, 8)}...</span>
                <span className="text-xs text-mgray/50 font-mono">{agent.model_id}</span>
              </div>
              <p className="text-xs text-mgray mt-1">{agent.description}</p>
            </div>
          </div>
          <div className="divide-y divide-blue/10">
            {Object.entries(scenarios[agent.id] ?? {}).map(([key, meta]) => {
              const runKey = `${agent.id}:${key}`;
              const isRunning = running === runKey;
              const result = results[runKey];
              const error  = errors[runKey];
              const expColor = EXPECTED_COLOR[meta.expected];
              return (
                <div key={key} className="px-5 py-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap mb-1">
                        <span className="text-sm font-semibold text-white">{meta.label}</span>
                        {expColor && <span className={`text-xs font-semibold ${expColor}`}>{t('result.expected', { label: t(`expected.${meta.expected}`) })}</span>}
                      </div>
                      <p className="text-xs text-mgray leading-relaxed">{meta.description}</p>
                    </div>
                    <button onClick={() => run(agent.id, key)} disabled={!!running}
                      className="flex-shrink-0 px-4 py-2 bg-teal text-dark text-sm font-semibold rounded-lg hover:bg-teal/90 disabled:opacity-40">
                      {isRunning ? t('result.running') : t('result.run')}
                    </button>
                  </div>
                  {error && <div className="mt-3 bg-red-900/20 border border-red-700 rounded-lg px-4 py-3 text-xs text-red-300">{error}</div>}
                  {result && (
                    <div className="mt-3 rounded-lg border border-blue/30 overflow-hidden">
                      <div className="bg-dark/60 px-4 py-2 flex items-center gap-3 flex-wrap border-b border-blue/20">
                        <PolicyBadge result={result.policy_result as PolicyResult} />
                        <span className="text-xs text-mgray">HTTP {result.http_status}</span>
                        <span className="text-xs text-mgray/50 font-mono truncate">{t('result.task', { id: result.task_id.slice(0, 8) })}</span>
                        {(result.policy_result === result.expected ||
                          (result.expected === 'allowed_with_pii' && result.policy_result === 'allowed'))
                          ? <span className="ml-auto text-xs text-green-400 font-semibold">{t('result.match')}</span>
                          : <span className="ml-auto text-xs text-yellow-400">{t('result.mismatch')}</span>}
                      </div>
                      <div className="px-4 py-3 bg-dark/40">
                        <div className="text-xs text-mgray/60 mb-1.5">{t('result.gatewayResponse')}</div>
                        <pre className="text-xs text-lgray leading-relaxed whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
                          {extractContent(result)}
                        </pre>
                      </div>
                      <div className="px-4 py-2 bg-dark/20 border-t border-blue/10 flex gap-4 text-xs">
                        <a href="/audit" className="text-teal hover:underline">{t('links.auditLog')}</a>
                        {result.policy_result === 'oversight_required' && (
                          <a href="/oversight" className="text-orange-400 hover:underline">{t('links.oversightQueue')}</a>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}

      {/* Agenci z wolnym czatem (DeepSeek i inne bez scenariuszy) */}
      {chatAgents.length > 0 && (
        <>
          <div className="flex items-center gap-3">
            <div className="flex-1 h-px bg-blue/20" />
            <span className="text-xs text-mgray px-2">{t('chat.sectionTitle')}</span>
            <div className="flex-1 h-px bg-blue/20" />
          </div>
          {chatAgents.map(agent => (
            <div key={agent.id} className="bg-navy border border-blue/30 rounded-xl overflow-hidden">
              <div className="px-5 py-4 border-b border-blue/20 flex items-start gap-3">
                <div className="flex-1">
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className="font-semibold text-white">{agent.name}</span>
                    <span className={`text-xs font-semibold px-2 py-0.5 rounded border uppercase ${RISK_STYLE[agent.risk_level]}`}>
                      {tc(`risk.${agent.risk_level}`)}
                    </span>
                    <span className="text-xs font-mono text-teal/70 border border-teal/20 px-2 py-0.5 rounded">
                      {agent.model_id}
                    </span>
                  </div>
                  <p className="text-xs text-mgray mt-1">{agent.description}</p>
                  <p className="text-xs text-mgray/50 mt-1">
                    {t('chat.pipeline', { model: agent.model_id })}
                  </p>
                </div>
              </div>
              <FreeChat agent={agent} />
            </div>
          ))}
        </>
      )}
    </div>
  );
}
