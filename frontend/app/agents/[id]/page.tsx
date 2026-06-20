'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { api, Agent, ComplianceReport, ComplianceDecl, DeclStatus } from '@/lib/api';
import RiskBadge from '@/components/RiskBadge';

type Tab = 'compliance' | 'stats' | 'registry';

// ── Deklaracje EU AI Act ───────────────────────────────────────────────────────

const AI_ACT_DECLS = [
  { key: 'art9_risk_management',   art: 'Art. 9',   title: 'System zarządzania ryzykiem',           desc: 'Udokumentowany proces identyfikacji, analizy i mitygacji ryzyk przez cały cykl życia.' },
  { key: 'art10_data_governance',  art: 'Art. 10',  title: 'Zarządzanie danymi treningowymi',       desc: 'Dane treningowe/testowe spełniają kryteria jakości, reprezentatywności i braku błędów.' },
  { key: 'art11_technical_docs',   art: 'Art. 11',  title: 'Dokumentacja techniczna',              desc: 'Kompletna dokumentacja techniczna zgodna z Aneksem IV EU AI Act, aktualizowana na bieżąco.' },
  { key: 'art13_transparency',     art: 'Art. 13',  title: 'Transparentność dla użytkowników',     desc: 'Użytkownicy są informowani o interakcji z AI i rozumieją możliwości/ograniczenia systemu.' },
  { key: 'art14_human_oversight',  art: 'Art. 14',  title: 'Nadzór człowieka',                     desc: 'Wdrożone środki umożliwiające rozumienie, monitorowanie i interwencję w działanie systemu.' },
  { key: 'art15_accuracy',         art: 'Art. 15',  title: 'Dokładność i cyberbezpieczeństwo',     desc: 'Przeprowadzone testy dokładności, solidności i odporności na cyberataki.' },
  { key: 'conformity_assessment',  art: 'Ocena',    title: 'Ocena zgodności (conformity assessment)', desc: 'Przeprowadzona ocena zgodności — własna lub przez jednostkę notyfikowaną.' },
  { key: 'eu_database_registered', art: 'Rejestr EU', title: 'Rejestracja w unijnej bazie AI',    desc: 'System zarejestrowany w unijnej bazie danych wysokiego ryzyka (wymagane dla Aneks III).' },
];

const DECL_STATUS_OPTS: { value: DeclStatus; label: string; color: string }[] = [
  { value: '',        label: '— nie oceniono —', color: 'text-mgray' },
  { value: 'yes',     label: '✓ Tak — spełnione', color: 'text-green-400' },
  { value: 'partial', label: '◑ Częściowo',        color: 'text-yellow-400' },
  { value: 'no',      label: '✗ Nie — luka',       color: 'text-red-400' },
  { value: 'na',      label: 'N/A — nie dotyczy',  color: 'text-mgray/60' },
];

const STATUS_COLOR: Record<string, string> = {
  yes:     'bg-green-900/20 border-green-700 text-green-400',
  partial: 'bg-yellow-900/20 border-yellow-700 text-yellow-400',
  no:      'bg-red-900/20 border-red-700 text-red-400',
  na:      'bg-dark/40 border-blue/20 text-mgray/60',
  '':      'bg-dark/40 border-blue/20 text-mgray/40',
};

const GDPR_BASES = [
  { value: 'consent',             label: 'Zgoda osoby (art. 6 ust. 1 lit. a)' },
  { value: 'contract',            label: 'Wykonanie umowy (art. 6 ust. 1 lit. b)' },
  { value: 'legal_obligation',    label: 'Obowiązek prawny (art. 6 ust. 1 lit. c)' },
  { value: 'vital_interests',     label: 'Ochrona żywotnych interesów (lit. d)' },
  { value: 'public_task',         label: 'Zadanie publiczne (art. 6 ust. 1 lit. e)' },
  { value: 'legitimate_interest', label: 'Prawnie uzasadniony interes (lit. f)' },
];

// ── Zakładka Rejestr ──────────────────────────────────────────────────────────

function RegistryTab({ agent, onSaved }: { agent: Agent; onSaved: (updated: Agent) => void }) {
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  // Inicjalizacja stanu formularza z danych agenta
  const [form, setForm] = useState({
    version:                  agent.version ?? '1.0.0',
    last_reviewed_at:         agent.last_reviewed_at?.slice(0, 10) ?? '',
    next_review_date:         agent.next_review_date ?? '',
    intended_purpose:         agent.intended_purpose ?? '',
    intended_users:           agent.intended_users ?? '',
    geographic_scope:         agent.geographic_scope ?? 'PL',
    model_version:            agent.model_version ?? '',
    processes_personal_data:  agent.processes_personal_data ?? false,
    gdpr_legal_basis:         agent.gdpr_legal_basis ?? '',
    data_retention_days:      String(agent.data_retention_days ?? ''),
    input_modalities:         (agent.input_modalities ?? ['text']).join(', '),
    output_modalities:        (agent.output_modalities ?? ['text']).join(', '),
    integration_points:       (agent.integration_points ?? []).join('\n'),
    technical_contact_email:  agent.technical_contact_email ?? '',
    compliance_officer_email: agent.compliance_officer_email ?? '',
    monthly_budget_eur:       String(agent.monthly_budget_eur ?? 0),
    cost_alert_threshold_eur: String(agent.cost_alert_threshold_eur ?? ''),
  });

  const [decl, setDecl] = useState<ComplianceDecl>(() => {
    const base = agent.compliance_decl ?? {};
    const result: ComplianceDecl = {};
    for (const d of AI_ACT_DECLS) {
      result[d.key] = base[d.key] ?? { status: '', notes: '' };
    }
    return result;
  });

  function setDeclField(key: string, field: 'status' | 'notes', value: string) {
    setDecl(prev => ({
      ...prev,
      [key]: { ...prev[key], [field]: value },
    }));
  }

  async function save() {
    setSaving(true);
    try {
      const body = {
        ...form,
        data_retention_days:      form.data_retention_days ? parseInt(form.data_retention_days) : null,
        monthly_budget_eur:       parseFloat(form.monthly_budget_eur) || 0,
        cost_alert_threshold_eur: form.cost_alert_threshold_eur ? parseFloat(form.cost_alert_threshold_eur) : null,
        input_modalities:         form.input_modalities.split(',').map(s => s.trim()).filter(Boolean),
        output_modalities:        form.output_modalities.split(',').map(s => s.trim()).filter(Boolean),
        integration_points:       form.integration_points.split('\n').map(s => s.trim()).filter(Boolean),
        last_reviewed_at:         form.last_reviewed_at || null,
        next_review_date:         form.next_review_date || null,
        compliance_decl:          decl,
      };
      const updated = await api.agents.updateRegistry(agent.id, body);
      onSaved(updated as Agent);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e) {
      alert(String(e));
    } finally {
      setSaving(false);
    }
  }

  function field(label: string, key: keyof typeof form, type: 'text' | 'email' | 'number' | 'date' = 'text', placeholder = '') {
    return (
      <div>
        <label className="text-xs text-mgray mb-1 block">{label}</label>
        <input
          type={type}
          className="w-full bg-dark border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal"
          placeholder={placeholder}
          value={form[key] as string}
          onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">

      {/* Sekcja: Podstawowe */}
      <Section title="Wersja i przeglądy">
        <div className="grid grid-cols-3 gap-4">
          {field('Wersja systemu', 'version', 'text', '1.0.0')}
          {field('Ostatni przegląd compliance', 'last_reviewed_at', 'date')}
          {field('Planowany następny przegląd', 'next_review_date', 'date')}
        </div>
        <div>
          <label className="text-xs text-mgray mb-1 block">Cel i zakres systemu (intended purpose)</label>
          <textarea rows={2} className="w-full bg-dark border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal resize-none"
            placeholder="Krótki opis do czego system służy i w jakim kontekście jest używany..."
            value={form.intended_purpose}
            onChange={e => setForm(f => ({ ...f, intended_purpose: e.target.value }))} />
        </div>
        <div className="grid grid-cols-2 gap-4">
          {field('Docelowi użytkownicy', 'intended_users', 'text', 'np. analitycy kredytowi, pracownicy HR')}
          {field('Zakres geograficzny', 'geographic_scope', 'text', 'np. PL, UE')}
        </div>
      </Section>

      {/* Sekcja: Deklaracje EU AI Act */}
      <Section title="Deklaracje zgodności EU AI Act">
        <p className="text-xs text-mgray -mt-1 mb-3">
          Ocena każdego artykułu przez odpowiedzialną osobę — widoczna w raportach PDF i ocenie zgodności.
        </p>
        <div className="space-y-3">
          {AI_ACT_DECLS.map(d => {
            const current = decl[d.key] ?? { status: '', notes: '' };
            const statusOpt = DECL_STATUS_OPTS.find(o => o.value === current.status);
            return (
              <div key={d.key} className={`border rounded-lg px-4 py-3 ${STATUS_COLOR[current.status] ?? STATUS_COLOR['']}`}>
                <div className="flex items-start gap-4 flex-wrap">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                      <span className="text-xs font-mono font-bold opacity-70">{d.art}</span>
                      <span className="text-sm font-semibold">{d.title}</span>
                    </div>
                    <p className="text-xs opacity-60 leading-relaxed">{d.desc}</p>
                  </div>
                  <div className="flex flex-col gap-2 flex-shrink-0 min-w-[180px]">
                    <select
                      className="bg-dark/60 border border-current/20 rounded-lg px-2 py-1.5 text-xs text-white focus:outline-none focus:border-teal"
                      value={current.status}
                      onChange={e => setDeclField(d.key, 'status', e.target.value)}
                    >
                      {DECL_STATUS_OPTS.map(o => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                      ))}
                    </select>
                  </div>
                </div>
                <div className="mt-2">
                  <input
                    className="w-full bg-dark/40 border border-current/10 rounded px-2 py-1 text-xs text-white/80 placeholder:text-mgray/40 focus:outline-none focus:border-teal"
                    placeholder="Notatka (opcjonalnie) — np. 'Dokumentacja w Confluence, space AI-GOV'"
                    value={current.notes}
                    onChange={e => setDeclField(d.key, 'notes', e.target.value)}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </Section>

      {/* Sekcja: Dane i RODO */}
      <Section title="Dane osobowe i RODO">
        <div className="flex items-center gap-3 mb-3">
          <button
            onClick={() => setForm(f => ({ ...f, processes_personal_data: !f.processes_personal_data }))}
            className={`relative w-10 h-5 rounded-full transition-colors ${form.processes_personal_data ? 'bg-teal' : 'bg-mgray/30'}`}
          >
            <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform ${form.processes_personal_data ? 'translate-x-5' : 'translate-x-0.5'}`} />
          </button>
          <label className="text-sm text-white">System przetwarza dane osobowe</label>
        </div>
        {form.processes_personal_data && (
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-mgray mb-1 block">Podstawa prawna RODO</label>
              <select
                className="w-full bg-dark border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal"
                value={form.gdpr_legal_basis}
                onChange={e => setForm(f => ({ ...f, gdpr_legal_basis: e.target.value }))}
              >
                <option value="">— wybierz —</option>
                {GDPR_BASES.map(b => <option key={b.value} value={b.value}>{b.label}</option>)}
              </select>
            </div>
            {field('Retencja danych (dni)', 'data_retention_days', 'number', 'np. 365')}
          </div>
        )}
      </Section>

      {/* Sekcja: Techniczne */}
      <Section title="Dane techniczne">
        <div className="grid grid-cols-3 gap-4">
          {field('Wersja modelu', 'model_version', 'text', 'np. claude-haiku-4-5-20251001')}
          {field('Modalności wejściowe (lista)', 'input_modalities', 'text', 'text, image')}
          {field('Modalności wyjściowe (lista)', 'output_modalities', 'text', 'text')}
        </div>
        <div>
          <label className="text-xs text-mgray mb-1 block">Punkty integracji (każdy w nowej linii)</label>
          <textarea rows={3} className="w-full bg-dark border border-blue/30 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-teal resize-none"
            placeholder={"Core Banking System (CBS)\nCRM Salesforce\nBaza BIK"}
            value={form.integration_points}
            onChange={e => setForm(f => ({ ...f, integration_points: e.target.value }))} />
        </div>
      </Section>

      {/* Sekcja: Kontakty i budżet */}
      <Section title="Kontakty i budżet">
        <div className="grid grid-cols-2 gap-4">
          {field('Kontakt techniczny', 'technical_contact_email', 'email', 'devops@bank.example.com')}
          {field('Oficer compliance', 'compliance_officer_email', 'email', 'compliance@bank.example.com')}
        </div>
        <div className="grid grid-cols-2 gap-4">
          {field('Miesięczny budżet (EUR)', 'monthly_budget_eur', 'number', '200')}
          {field('Próg alertu budżetowego (EUR)', 'cost_alert_threshold_eur', 'number', 'np. 160 = alert przy 80%')}
        </div>
      </Section>

      {/* Zapis */}
      <div className="flex items-center gap-4">
        <button
          onClick={save}
          disabled={saving}
          className="px-6 py-2.5 bg-teal text-dark font-semibold rounded-lg hover:bg-teal/90 disabled:opacity-40 transition-colors"
        >
          {saving ? 'Zapisywanie...' : 'Zapisz rejestr'}
        </button>
        {saved && (
          <span className="text-sm text-green-400">✓ Zapisano pomyślnie</span>
        )}
        <span className="text-xs text-mgray ml-auto">
          Ostatnia aktualizacja: {agent.updated_at ? new Date(agent.updated_at).toLocaleString('pl-PL') : '—'}
        </span>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-navy border border-blue/30 rounded-xl p-5 space-y-4">
      <h3 className="text-sm font-semibold text-white border-b border-blue/20 pb-2">{title}</h3>
      {children}
    </div>
  );
}

// ── Strona główna ─────────────────────────────────────────────────────────────

export default function AgentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [agent, setAgent] = useState<Agent | null>(null);
  const [compliance, setCompliance] = useState<ComplianceReport | null>(null);
  const [stats, setStats] = useState<Record<string, unknown> | null>(null);
  const [tab, setTab] = useState<Tab>('compliance');

  useEffect(() => {
    api.agents.get(id).then(setAgent).catch(console.error);
    api.agents.compliance(id).then(setCompliance).catch(console.error);
    api.agents.stats(id, 30).then(setStats).catch(console.error);
  }, [id]);

  if (!agent) return <div className="text-mgray animate-pulse">Ładowanie...</div>;

  const statusColor: Record<string, string> = {
    active: 'text-green-400', suspended: 'text-yellow-400',
    quarantined: 'text-red-400', retired: 'text-mgray/50',
  };

  const severityColor: Record<string, string> = {
    critical: 'border-red-700 bg-red-900/20 text-red-300',
    major:    'border-orange-700 bg-orange-900/20 text-orange-300',
    minor:    'border-yellow-700 bg-yellow-900/20 text-yellow-300',
  };

  const totals = stats?.totals as Record<string, number> | undefined;

  // Liczba deklaracji wypełnionych do wyświetlenia w zakładce
  const declFilled = Object.values(agent.compliance_decl ?? {})
    .filter(v => v?.status && v.status !== '').length;

  return (
    <div className="space-y-6 max-w-5xl">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-mgray">
        <Link href="/agents" className="hover:text-teal">Agenci</Link>
        <span>/</span>
        <span className="text-white">{agent.name}</span>
      </div>

      {/* Profil */}
      <div className="bg-navy border border-blue/30 rounded-xl p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-2xl font-bold text-white">{agent.name}</h1>
              <RiskBadge level={agent.risk_level} />
              <span className={`text-xs font-semibold ${statusColor[agent.status] ?? 'text-mgray'}`}>
                {agent.status.toUpperCase()}
              </span>
              {agent.version && (
                <span className="text-xs font-mono text-mgray/60 border border-blue/20 px-2 py-0.5 rounded">
                  v{agent.version}
                </span>
              )}
            </div>
            <p className="text-mgray text-sm mt-2 leading-relaxed max-w-2xl">{agent.description}</p>
          </div>
          {agent.requires_oversight && (
            <div className="flex-shrink-0 bg-orange-900/30 border border-orange-700 rounded-lg px-3 py-2 text-xs text-orange-300 text-center">
              <div className="text-lg mb-0.5">◎</div>
              <div>Nadzór<br/>wymagany</div>
            </div>
          )}
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6 pt-5 border-t border-blue/20">
          {[
            { label: 'Właściciel',    value: agent.owner_name },
            { label: 'Zespół',        value: agent.team || '—' },
            { label: 'Model',         value: agent.model_id },
            { label: 'Budżet / mies', value: `${agent.monthly_budget_eur} EUR` },
          ].map(({ label, value }) => (
            <div key={label}>
              <div className="text-xs text-mgray mb-0.5">{label}</div>
              <div className="text-sm text-white font-medium">{value}</div>
            </div>
          ))}
        </div>

        {agent.legal_basis && (
          <div className="mt-4 bg-dark/50 rounded-lg px-4 py-3 text-xs text-mgray border border-blue/20">
            <span className="text-teal font-semibold">Podstawa prawna: </span>
            {agent.legal_basis}
          </div>
        )}

        {/* Przegląd compliance — daty */}
        {(agent.last_reviewed_at || agent.next_review_date) && (
          <div className="mt-3 flex gap-6 text-xs text-mgray">
            {agent.last_reviewed_at && (
              <span>Ostatni przegląd: <span className="text-white">{new Date(agent.last_reviewed_at).toLocaleDateString('pl-PL')}</span></span>
            )}
            {agent.next_review_date && (
              <span>Następny: <span className={
                new Date(agent.next_review_date) < new Date() ? 'text-red-400' : 'text-green-400'
              }>{new Date(agent.next_review_date).toLocaleDateString('pl-PL')}</span></span>
            )}
          </div>
        )}
      </div>

      {/* Raport button */}
      <div className="flex justify-end">
        <Link
          href={`/agents/${id}/report`}
          className="px-4 py-2 text-sm bg-teal text-dark font-semibold rounded-lg hover:bg-teal/90 transition-colors"
        >
          Generuj raport PDF →
        </Link>
      </div>

      {/* Zakładki */}
      <div className="flex gap-1 border-b border-blue/30">
        {([
          { key: 'compliance', label: 'Zgodność AI Act' },
          { key: 'stats',      label: 'Statystyki 30 dni' },
          { key: 'registry',   label: `Rejestr${declFilled > 0 ? ` (${declFilled}/${AI_ACT_DECLS.length})` : ''}` },
        ] as { key: Tab; label: string }[]).map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              tab === key
                ? 'border-teal text-teal'
                : 'border-transparent text-mgray hover:text-white'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Zakładka: Zgodność */}
      {tab === 'compliance' && compliance && (
        <div className="space-y-4">
          <div className={`rounded-lg px-5 py-3 border text-sm font-semibold ${
            compliance.status === 'compliant' ? 'bg-green-900/30 border-green-700 text-green-300' :
            compliance.status === 'critical'  ? 'bg-red-900/30 border-red-700 text-red-300' :
                                                'bg-orange-900/30 border-orange-700 text-orange-300'
          }`}>
            {compliance.summary}
          </div>

          {compliance.gaps.length > 0 && (
            <div className="space-y-3">
              <h3 className="text-sm font-semibold text-white">Wykryte luki ({compliance.gaps.length})</h3>
              {compliance.gaps.map((gap, i) => (
                <div key={i} className={`rounded-lg border px-4 py-3 ${severityColor[gap.severity]}`}>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-bold bg-current/20 px-2 py-0.5 rounded">{gap.article}</span>
                    <span className="text-sm font-semibold">{gap.title}</span>
                    <span className="ml-auto text-xs opacity-70">Termin: {gap.deadline_days} dni</span>
                  </div>
                  <p className="text-xs opacity-80 mb-2">{gap.description}</p>
                  <div className="text-xs font-medium">→ {gap.action}</div>
                </div>
              ))}
            </div>
          )}

          {compliance.obligations.length > 0 && (
            <div className="bg-navy border border-blue/30 rounded-lg p-4">
              <h3 className="text-sm font-semibold text-white mb-3">Obowiązki prawne</h3>
              <ul className="space-y-1.5">
                {compliance.obligations.map((ob, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-mgray">
                    <span className="text-teal mt-0.5 flex-shrink-0">●</span>
                    {ob}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Zakładka: Statystyki */}
      {tab === 'stats' && stats && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: 'Wywołania',  value: totals?.total_calls ?? 0,    color: 'text-teal' },
              { label: 'Blokady',    value: totals?.blocked_calls ?? 0,  color: 'text-red-400' },
              { label: 'Do nadzoru', value: totals?.oversight_calls ?? 0, color: 'text-orange-400' },
              { label: 'Z PII',      value: totals?.pii_calls ?? 0,      color: 'text-yellow-400' },
            ].map(({ label, value, color }) => (
              <div key={label} className="bg-navy border border-blue/30 rounded-lg p-4">
                <div className="text-xs text-mgray mb-1">{label}</div>
                <div className={`text-2xl font-bold ${color}`}>{value}</div>
              </div>
            ))}
          </div>
          <div className="grid grid-cols-3 gap-4">
            {[
              { label: 'Śr. latencja', value: totals?.avg_latency_ms ? `${totals.avg_latency_ms} ms` : '—' },
              { label: 'Łączny koszt', value: totals?.total_cost_eur ? `${Number(totals.total_cost_eur).toFixed(4)} EUR` : '0 EUR' },
              { label: 'Wykryte PII',  value: totals?.total_pii_detected ?? 0 },
            ].map(({ label, value }) => (
              <div key={label} className="bg-navy border border-blue/30 rounded-lg px-4 py-3">
                <div className="text-xs text-mgray mb-0.5">{label}</div>
                <div className="text-sm font-semibold text-white">{String(value)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Zakładka: Rejestr */}
      {tab === 'registry' && (
        <RegistryTab agent={agent} onSaved={setAgent} />
      )}
    </div>
  );
}
