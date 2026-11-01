'use client';

import { useEffect, useRef, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { useTranslations } from 'next-intl';
import { api, Agent, AiActRequirement, ComplianceReport, ComplianceDecl, DeclStatus } from '@/lib/api';
import RiskBadge from '@/components/RiskBadge';
import { useFormat } from '@/lib/format';

type Tab = 'compliance' | 'stats' | 'registry';

// Wymagania z auto-checkiem — status liczony z faktu w rejestrze agenta, nie
// z samo-deklaracji. Musi być spójne z api/services/compliance.py:_AUTO_CHECKS
// (klucz → funkcja ORAZ etykieta wyjaśniająca skąd bierze się status —
// etykiety w messages: agents.options.autoCheck.<klucz>).
const AUTO_CHECK_RESOLVERS: Record<string, (agent: Agent) => 'yes' | 'no'> = {
  art14_human_oversight:   agent => (agent.requires_oversight ? 'yes' : 'no'),
  art26_2_human_oversight: agent => (agent.requires_oversight ? 'yes' : 'no'),
  art26_6_log_retention:   () => 'yes',
};

// Etykiety: agents.options.declStatus.<labelKey>
const DECL_STATUS_OPTS: { value: DeclStatus; labelKey: string; color: string }[] = [
  { value: '',        labelKey: 'none',    color: 'text-mgray' },
  { value: 'yes',     labelKey: 'yes',     color: 'text-green-400' },
  { value: 'partial', labelKey: 'partial', color: 'text-yellow-400' },
  { value: 'no',      labelKey: 'no',      color: 'text-red-400' },
  { value: 'na',      labelKey: 'na',      color: 'text-mgray/60' },
];

const STATUS_COLOR: Record<string, string> = {
  yes:        'bg-green-900/20 border-green-700 text-green-400',
  partial:    'bg-yellow-900/20 border-yellow-700 text-yellow-400',
  no:         'bg-red-900/20 border-red-700 text-red-400',
  na:         'bg-dark/40 border-blue/20 text-mgray/60',
  undeclared: 'bg-dark/40 border-orange-700/40 text-orange-300/90',
  '':         'bg-dark/40 border-blue/20 text-mgray/40',
};

// Etykiety: agents.options.requirementStatus.<status>
const REQUIREMENT_STATUSES = ['yes', 'partial', 'no', 'na', 'undeclared'];

// Etykiety: agents.options.gdprBasis.<value>
const GDPR_BASES = [
  'consent', 'contract', 'legal_obligation', 'vital_interests', 'public_task', 'legitimate_interest',
];

// ── Zakładka Rejestr ──────────────────────────────────────────────────────────

function RegistryTab({ agent, onSaved }: { agent: Agent; onSaved: (updated: Agent) => void }) {
  const t = useTranslations('agents');
  const tc = useTranslations('common');
  const fmt = useFormat();
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

  const [decl, setDecl] = useState<ComplianceDecl>(agent.compliance_decl ?? {});
  const [requirements, setRequirements] = useState<AiActRequirement[]>([]);
  const [reqLoading, setReqLoading] = useState(true);

  // Katalog wymagań — z bazy (ai_act_requirements), filtrowany wg risk_level
  // TEGO agenta. Edytowalny w Polityki → Wymagania EU AI Act; zmiana tam
  // natychmiast zmienia listę deklaracji tutaj, bez zmian w kodzie.
  useEffect(() => {
    setReqLoading(true);
    api.compliance.list(agent.risk_level, true)
      .then(setRequirements)
      .catch(console.error)
      .finally(() => setReqLoading(false));
  }, [agent.risk_level]);

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

  const riskLabel = tc(`risk.${agent.risk_level}`);

  return (
    <div className="space-y-6">

      {/* Sekcja: Podstawowe */}
      <Section title={t('registry.sections.versionReviews')}>
        <div className="grid grid-cols-3 gap-4">
          {field(t('registry.fields.version'), 'version', 'text', '1.0.0')}
          {field(t('registry.fields.lastReviewedAt'), 'last_reviewed_at', 'date')}
          {field(t('registry.fields.nextReviewDate'), 'next_review_date', 'date')}
        </div>
        <div>
          <label className="text-xs text-mgray mb-1 block">{t('registry.fields.intendedPurpose')}</label>
          <textarea rows={2} className="w-full bg-dark border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal resize-none"
            placeholder={t('registry.fields.intendedPurposePlaceholder')}
            value={form.intended_purpose}
            onChange={e => setForm(f => ({ ...f, intended_purpose: e.target.value }))} />
        </div>
        <div className="grid grid-cols-2 gap-4">
          {field(t('registry.fields.intendedUsers'), 'intended_users', 'text', t('registry.fields.intendedUsersPlaceholder'))}
          {field(t('registry.fields.geographicScope'), 'geographic_scope', 'text', t('registry.fields.geographicScopePlaceholder'))}
        </div>
      </Section>

      {/* Sekcja: Deklaracje EU AI Act */}
      <Section title={t('registry.sections.declarations')}>
        <p className="text-xs text-mgray -mt-1 mb-3">
          {t('registry.declarationsIntro', { risk: riskLabel })}
        </p>
        {reqLoading ? (
          <p className="text-xs text-mgray/50 italic">{t('registry.loadingRequirements')}</p>
        ) : requirements.length === 0 ? (
          <p className="text-xs text-mgray/50 italic">
            {t('registry.noRequirements', { risk: riskLabel })}
          </p>
        ) : (
          <div className="space-y-3">
            {requirements.map(req => {
              const autoResolver = req.decl_key ? AUTO_CHECK_RESOLVERS[req.decl_key] : undefined;
              const noDecl = !req.decl_key;

              // Auto-check: status pochodzi z faktu rejestru (per-klucz resolver
              // zgodny z api/services/compliance.py:_AUTO_CHECKS), nie z
              // samo-deklaracji — pokazujemy tylko do odczytu.
              if (autoResolver) {
                const autoStatus = autoResolver(agent);
                // Każdy klucz z AUTO_CHECK_RESOLVERS ma etykietę w options.autoCheck
                const label = t(`options.autoCheck.${req.decl_key as string}`);
                return (
                  <div key={req.id} className={`border rounded-lg px-4 py-3 ${STATUS_COLOR[autoStatus]}`}>
                    <div className="flex items-start gap-4 flex-wrap">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                          <span className="text-xs font-mono font-bold opacity-70">{req.article_ref}</span>
                          <span className="text-sm font-semibold">{req.requirement_title}</span>
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue/20 text-blue-300">{t('registry.automatic')}</span>
                        </div>
                        <p className="text-xs opacity-60 leading-relaxed">{req.requirement_text}</p>
                      </div>
                      <div className="flex-shrink-0 min-w-[180px] text-xs font-semibold">
                        {autoStatus === 'yes' ? t('registry.autoStatusMet') : t('registry.autoStatusGap')} — {label}
                      </div>
                    </div>
                  </div>
                );
              }

              // Bez decl_key (np. Art. 5 dla niedopuszczalnego ryzyka) — nie da
              // się tego "samo-zadeklarować", tylko usunąć realny problem.
              if (noDecl) {
                return (
                  <div key={req.id} className="border rounded-lg px-4 py-3 bg-red-900/20 border-red-700 text-red-300">
                    <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                      <span className="text-xs font-mono font-bold opacity-70">{req.article_ref}</span>
                      <span className="text-sm font-semibold">{req.requirement_title}</span>
                    </div>
                    <p className="text-xs opacity-80 leading-relaxed">{req.requirement_text}</p>
                    <p className="text-xs mt-1 italic opacity-70">{t('registry.notSelfDeclarable')}</p>
                  </div>
                );
              }

              const key = req.decl_key as string;
              const current = decl[key] ?? { status: '', notes: '' };
              return (
                <div key={req.id} className={`border rounded-lg px-4 py-3 ${STATUS_COLOR[current.status] ?? STATUS_COLOR['']}`}>
                  <div className="flex items-start gap-4 flex-wrap">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                        <span className="text-xs font-mono font-bold opacity-70">{req.article_ref}</span>
                        <span className="text-sm font-semibold">{req.requirement_title}</span>
                      </div>
                      <p className="text-xs opacity-60 leading-relaxed">{req.requirement_text}</p>
                    </div>
                    <div className="flex flex-col gap-2 flex-shrink-0 min-w-[180px]">
                      <select
                        className="bg-dark/60 border border-current/20 rounded-lg px-2 py-1.5 text-xs text-white focus:outline-none focus:border-teal"
                        value={current.status}
                        onChange={e => setDeclField(key, 'status', e.target.value)}
                      >
                        {DECL_STATUS_OPTS.map(o => (
                          <option key={o.value} value={o.value}>{t(`options.declStatus.${o.labelKey}`)}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <div className="mt-2">
                    <input
                      className="w-full bg-dark/40 border border-current/10 rounded px-2 py-1 text-xs text-white/80 placeholder:text-mgray/40 focus:outline-none focus:border-teal"
                      placeholder={t('registry.notePlaceholder')}
                      value={current.notes}
                      onChange={e => setDeclField(key, 'notes', e.target.value)}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Section>

      {/* Sekcja: Dane i RODO */}
      <Section title={t('registry.sections.personalData')}>
        <div className="flex items-center gap-3 mb-3">
          <button
            onClick={() => setForm(f => ({ ...f, processes_personal_data: !f.processes_personal_data }))}
            className={`relative w-10 h-5 rounded-full transition-colors ${form.processes_personal_data ? 'bg-teal' : 'bg-mgray/30'}`}
          >
            <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform ${form.processes_personal_data ? 'translate-x-5' : 'translate-x-0.5'}`} />
          </button>
          <label className="text-sm text-white">{t('registry.fields.processesPersonalData')}</label>
        </div>
        {form.processes_personal_data && (
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-mgray mb-1 block">{t('registry.fields.gdprLegalBasis')}</label>
              <select
                className="w-full bg-dark border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal"
                value={form.gdpr_legal_basis}
                onChange={e => setForm(f => ({ ...f, gdpr_legal_basis: e.target.value }))}
              >
                <option value="">{t('registry.fields.selectPlaceholder')}</option>
                {GDPR_BASES.map(b => <option key={b} value={b}>{t(`options.gdprBasis.${b}`)}</option>)}
              </select>
            </div>
            {field(t('registry.fields.dataRetentionDays'), 'data_retention_days', 'number', t('registry.fields.dataRetentionDaysPlaceholder'))}
          </div>
        )}
      </Section>

      {/* Sekcja: Techniczne */}
      <Section title={t('registry.sections.technical')}>
        <div className="grid grid-cols-3 gap-4">
          {field(t('registry.fields.modelVersion'), 'model_version', 'text', t('registry.fields.modelVersionPlaceholder'))}
          {field(t('registry.fields.inputModalities'), 'input_modalities', 'text', 'text, image')}
          {field(t('registry.fields.outputModalities'), 'output_modalities', 'text', 'text')}
        </div>
        <div>
          <label className="text-xs text-mgray mb-1 block">{t('registry.fields.integrationPoints')}</label>
          <textarea rows={3} className="w-full bg-dark border border-blue/30 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-teal resize-none"
            placeholder={t('registry.fields.integrationPointsPlaceholder')}
            value={form.integration_points}
            onChange={e => setForm(f => ({ ...f, integration_points: e.target.value }))} />
        </div>
      </Section>

      {/* Sekcja: Kontakty i budżet */}
      <Section title={t('registry.sections.contactsBudget')}>
        <div className="grid grid-cols-2 gap-4">
          {field(t('registry.fields.technicalContact'), 'technical_contact_email', 'email', 'devops@bank.example.com')}
          {field(t('registry.fields.complianceOfficer'), 'compliance_officer_email', 'email', 'compliance@bank.example.com')}
        </div>
        <div className="grid grid-cols-2 gap-4">
          {field(t('registry.fields.monthlyBudget'), 'monthly_budget_eur', 'number', '200')}
          {field(t('registry.fields.costAlertThreshold'), 'cost_alert_threshold_eur', 'number', t('registry.fields.costAlertThresholdPlaceholder'))}
        </div>
      </Section>

      {/* Zapis */}
      <div className="flex items-center gap-4">
        <button
          onClick={save}
          disabled={saving}
          className="px-6 py-2.5 bg-teal text-dark font-semibold rounded-lg hover:bg-teal/90 disabled:opacity-40 transition-colors"
        >
          {saving ? t('registry.saving') : t('registry.save')}
        </button>
        {saved && (
          <span className="text-sm text-green-400">{t('registry.saved')}</span>
        )}
        <span className="text-xs text-mgray ml-auto">
          {t('registry.lastUpdated', { date: agent.updated_at ? fmt.dateTime(agent.updated_at) : '—' })}
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
  const t = useTranslations('agents');
  const tc = useTranslations('common');
  const fmt = useFormat();
  const { id } = useParams<{ id: string }>();
  const [agent, setAgent] = useState<Agent | null>(null);
  const [compliance, setCompliance] = useState<ComplianceReport | null>(null);
  const [stats, setStats] = useState<Record<string, unknown> | null>(null);
  const [tab, setTab] = useState<Tab>('compliance');
  const prevTab = useRef<Tab>('compliance');

  function loadAll() {
    api.agents.get(id).then(setAgent).catch(console.error);
    api.agents.compliance(id).then(setCompliance).catch(console.error);
    api.agents.stats(id, 30).then(setStats).catch(console.error);
  }

  useEffect(loadAll, [id]);

  // Zakładka Rejestr zapisuje dane, które zmieniają wynik oceny zgodności
  // (compliance_decl, requires_oversight itd.) — przy wyjściu z niej do innej
  // zakładki odśwież wszystko, żeby nie pokazywać stanu sprzed zapisu.
  useEffect(() => {
    if (prevTab.current === 'registry' && tab !== 'registry') {
      loadAll();
    }
    prevTab.current = tab;
  }, [tab]);

  if (!agent) return <div className="text-mgray animate-pulse">{t('detail.loading')}</div>;

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
    .filter(v => v?.status).length;

  const requirementStatusLabel = (s: string) =>
    REQUIREMENT_STATUSES.includes(s) ? t(`options.requirementStatus.${s}`) : s;

  return (
    <div className="space-y-6 max-w-5xl">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-mgray">
        <Link href="/agents" className="hover:text-teal">{t('detail.breadcrumb')}</Link>
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
                {tc(`agentStatus.${agent.status}`).toUpperCase()}
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
              <div>{t.rich('detail.oversightRequired', { br: () => <br /> })}</div>
            </div>
          )}
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6 pt-5 border-t border-blue/20">
          {[
            { label: t('detail.profile.owner'),          value: agent.owner_name },
            { label: t('detail.profile.team'),           value: agent.team || '—' },
            { label: t('detail.profile.model'),          value: agent.model_id },
            { label: t('detail.profile.budgetPerMonth'), value: t('detail.profile.budgetValue', { amount: agent.monthly_budget_eur }) },
          ].map(({ label, value }) => (
            <div key={label}>
              <div className="text-xs text-mgray mb-0.5">{label}</div>
              <div className="text-sm text-white font-medium">{value}</div>
            </div>
          ))}
        </div>

        {agent.legal_basis && (
          <div className="mt-4 bg-dark/50 rounded-lg px-4 py-3 text-xs text-mgray border border-blue/20">
            <span className="text-teal font-semibold">{t('detail.profile.legalBasis')}</span>
            {agent.legal_basis}
          </div>
        )}

        {/* Przegląd compliance — daty */}
        {(agent.last_reviewed_at || agent.next_review_date) && (
          <div className="mt-3 flex gap-6 text-xs text-mgray">
            {agent.last_reviewed_at && (
              <span>{t('detail.profile.lastReview')}<span className="text-white">{fmt.date(agent.last_reviewed_at)}</span></span>
            )}
            {agent.next_review_date && (
              <span>{t('detail.profile.nextReview')}<span className={
                new Date(agent.next_review_date) < new Date() ? 'text-red-400' : 'text-green-400'
              }>{fmt.date(agent.next_review_date)}</span></span>
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
          {t('detail.generateReport')}
        </Link>
      </div>

      {/* Zakładki */}
      <div className="flex gap-1 border-b border-blue/30">
        {([
          { key: 'compliance', label: t('detail.tabs.compliance') },
          { key: 'stats',      label: t('detail.tabs.stats') },
          { key: 'registry',   label: declFilled > 0
              ? t('detail.tabs.registryWithCount', { count: declFilled })
              : t('detail.tabs.registry') },
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

          {/* Profil systemu — widoczny niezależnie od poziomu ryzyka */}
          <div className="bg-navy border border-blue/30 rounded-lg p-4 space-y-3">
            <h3 className="text-sm font-semibold text-white">{t('detail.compliance.systemProfile')}</h3>
            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <div className="text-xs text-mgray mb-0.5">{t('detail.compliance.intendedPurpose')}</div>
                <div className="text-sm text-white/90">
                  {agent.intended_purpose || <span className="text-mgray/50 italic">{t('detail.compliance.notFilled')}</span>}
                </div>
              </div>
              <div>
                <div className="text-xs text-mgray mb-0.5">{t('detail.compliance.intendedUsers')}</div>
                <div className="text-sm text-white/90">{agent.intended_users || '—'}</div>
              </div>
              <div>
                <div className="text-xs text-mgray mb-0.5">{t('detail.compliance.geographicScope')}</div>
                <div className="text-sm text-white/90">{agent.geographic_scope || '—'}</div>
              </div>
              <div>
                <div className="text-xs text-mgray mb-0.5">{t('detail.compliance.personalData')}</div>
                <div className="text-sm text-white/90">
                  {agent.processes_personal_data
                    ? <>{t('detail.compliance.personalDataYes')}{agent.gdpr_legal_basis
                        ? (GDPR_BASES.includes(agent.gdpr_legal_basis) ? t(`options.gdprBasis.${agent.gdpr_legal_basis}`) : agent.gdpr_legal_basis)
                        : <span className="text-yellow-400">{t('detail.compliance.missingLegalBasis')}</span>}</>
                    : t('detail.compliance.personalDataNo')}
                </div>
              </div>
              <div>
                <div className="text-xs text-mgray mb-0.5">{t('detail.compliance.dataRetention')}</div>
                <div className="text-sm text-white/90">
                  {agent.data_retention_days ? t('detail.compliance.dataRetentionValue', { days: agent.data_retention_days }) : '—'}
                </div>
              </div>
              {agent.integration_points && agent.integration_points.length > 0 && (
                <div className="col-span-2">
                  <div className="text-xs text-mgray mb-1">{t('detail.compliance.integrationPoints')}</div>
                  <div className="flex flex-wrap gap-1.5">
                    {agent.integration_points.map((p, i) => (
                      <span key={i} className="text-xs bg-dark/60 border border-blue/20 rounded px-2 py-0.5 text-mgray">{p}</span>
                    ))}
                  </div>
                </div>
              )}
              <div>
                <div className="text-xs text-mgray mb-0.5">{t('detail.compliance.technicalContact')}</div>
                <div className="text-sm text-white/90">{agent.technical_contact_email || '—'}</div>
              </div>
              <div>
                <div className="text-xs text-mgray mb-0.5">{t('detail.compliance.complianceOfficer')}</div>
                <div className="text-sm text-white/90">{agent.compliance_officer_email || '—'}</div>
              </div>
            </div>
          </div>

          {compliance.requirements.length > 0 && (
            <div className="space-y-3">
              <h3 className="text-sm font-semibold text-white">
                {t('detail.compliance.requirementsHeading', {
                  met: compliance.requirements.length - compliance.gaps_count,
                  total: compliance.requirements.length,
                })}
              </h3>
              {compliance.requirements.map((req, i) => {
                const isGap = req.status === 'no' || req.status === 'partial' || req.status === 'undeclared';
                return (
                  <div key={i} className={`rounded-lg border px-4 py-3 ${
                    isGap ? (severityColor[req.severity] ?? severityColor.minor) : STATUS_COLOR.yes
                  }`}>
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <span className="text-xs font-bold bg-current/20 px-2 py-0.5 rounded">{req.article}</span>
                      <span className="text-sm font-semibold">{req.title}</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-current/10">{requirementStatusLabel(req.status)}</span>
                      {req.source === 'auto' && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue/20 text-blue-300">{t('detail.compliance.automatic')}</span>
                      )}
                      {isGap && (
                        <span className="ml-auto text-xs opacity-70">
                          {req.deadline_days === 0
                            ? t('detail.compliance.immediately')
                            : t('detail.compliance.deadline', { days: req.deadline_days })}
                        </span>
                      )}
                    </div>
                    <p className="text-xs opacity-80 mb-1">{req.description}</p>
                    {req.notes && <p className="text-xs opacity-60 italic">{t('detail.compliance.note', { notes: req.notes })}</p>}
                    {req.status === 'undeclared' && (
                      <div className="text-xs font-medium mt-1">{t('detail.compliance.fillDeclaration')}</div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Zakładka: Statystyki */}
      {tab === 'stats' && stats && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: t('detail.stats.calls'),     value: totals?.total_calls ?? 0,    color: 'text-teal' },
              { label: t('detail.stats.blocked'),   value: totals?.blocked_calls ?? 0,  color: 'text-red-400' },
              { label: t('detail.stats.oversight'), value: totals?.oversight_calls ?? 0, color: 'text-orange-400' },
              { label: t('detail.stats.pii'),       value: totals?.pii_calls ?? 0,      color: 'text-yellow-400' },
            ].map(({ label, value, color }) => (
              <div key={label} className="bg-navy border border-blue/30 rounded-lg p-4">
                <div className="text-xs text-mgray mb-1">{label}</div>
                <div className={`text-2xl font-bold ${color}`}>{value}</div>
              </div>
            ))}
          </div>
          <div className="grid grid-cols-3 gap-4">
            {[
              { label: t('detail.stats.avgLatency'),  value: totals?.avg_latency_ms ? `${totals.avg_latency_ms} ms` : '—' },
              { label: t('detail.stats.totalCost'),   value: totals?.total_cost_eur ? `${Number(totals.total_cost_eur).toFixed(4)} EUR` : '0 EUR' },
              { label: t('detail.stats.piiDetected'), value: totals?.total_pii_detected ?? 0 },
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
