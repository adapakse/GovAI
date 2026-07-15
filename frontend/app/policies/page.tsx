'use client';

import { useEffect, useMemo, useState } from 'react';
import { api, Policy, AiActRequirement, RiskLevel } from '@/lib/api';
import SearchBox from '@/components/SearchBox';
import { matchesQuery } from '@/lib/search';

type Tab = 'rules' | 'aiact';

const RISK_ORDER: RiskLevel[] = ['unacceptable', 'high', 'limited', 'minimal'];

const RISK_LABEL: Record<RiskLevel, string> = {
  unacceptable: 'Niedopuszczalne',
  high:         'Wysokie',
  limited:      'Ograniczone',
  minimal:      'Minimalne',
};

const RISK_STYLE: Record<RiskLevel, string> = {
  unacceptable: 'text-red-400 border-red-800 bg-red-900/20',
  high:         'text-orange-300 border-orange-800 bg-orange-900/20',
  limited:      'text-blue-300 border-blue-800 bg-blue-900/20',
  minimal:      'text-green-400 border-green-800 bg-green-900/20',
};

const SEVERITY_LABEL: Record<string, string> = { critical: 'Krytyczna', major: 'Poważna', minor: 'Drobna' };
const SEVERITY_BADGE: Record<string, string> = {
  critical: 'bg-red-900/30 text-red-300',
  major:    'bg-orange-900/30 text-orange-300',
  minor:    'bg-yellow-900/30 text-yellow-300',
};

// ── Formularz nowej polityki ──────────────────────────────────────────────────

function NewPolicyForm({ onSaved }: { onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    name: '', policy_code: '', keywords: '', reason: '', priority: '10',
  });

  async function save() {
    if (!form.name || !form.keywords) return;
    setSaving(true);
    try {
      await api.policies.create({
        name:          form.name,
        policy_code:   form.policy_code || null,
        level:         'org',
        rule_type:     'deny',
        condition_json: { keywords: form.keywords.split('\n').map(k => k.trim()).filter(Boolean) },
        action_json:   { reason: form.reason || `Zablokowane przez regułę ${form.policy_code}` },
        priority:      parseInt(form.priority) || 10,
        created_by:    'consultant',
      });
      setOpen(false);
      setForm({ name: '', policy_code: '', keywords: '', reason: '', priority: '10' });
      onSaved();
    } catch (e) {
      alert(String(e));
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="mt-4 px-4 py-2 border border-dashed border-blue/40 text-teal text-sm rounded-lg hover:border-teal/60 hover:bg-teal/5 transition-colors"
      >
        + Dodaj nową regułę
      </button>
    );
  }

  return (
    <div className="mt-4 bg-dark/60 border border-blue/30 rounded-xl p-5 space-y-4">
      <div className="font-semibold text-white text-sm">Nowa reguła blokująca</div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-xs text-mgray mb-1 block">Nazwa *</label>
          <input
            className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal"
            placeholder="np. Blokada eksportu danych"
            value={form.name}
            onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
          />
        </div>
        <div>
          <label className="text-xs text-mgray mb-1 block">Kod reguły</label>
          <input
            className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-teal"
            placeholder="np. G-003"
            value={form.policy_code}
            onChange={e => setForm(f => ({ ...f, policy_code: e.target.value }))}
          />
        </div>
      </div>
      <div>
        <label className="text-xs text-mgray mb-1 block">Słowa kluczowe (jedno na linię) *</label>
        <textarea
          rows={4}
          className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-teal resize-none"
          placeholder={"eksportuj dane\nexport data\nsend all records"}
          value={form.keywords}
          onChange={e => setForm(f => ({ ...f, keywords: e.target.value }))}
        />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-xs text-mgray mb-1 block">Komunikat blokady</label>
          <input
            className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal"
            placeholder="Wykryto niedozwoloną operację"
            value={form.reason}
            onChange={e => setForm(f => ({ ...f, reason: e.target.value }))}
          />
        </div>
        <div>
          <label className="text-xs text-mgray mb-1 block">Priorytet (niższy = ważniejszy)</label>
          <input
            type="number"
            className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal"
            value={form.priority}
            onChange={e => setForm(f => ({ ...f, priority: e.target.value }))}
          />
        </div>
      </div>
      <div className="flex gap-3">
        <button
          onClick={save}
          disabled={saving || !form.name || !form.keywords}
          className="px-4 py-2 bg-teal text-dark text-sm font-semibold rounded-lg hover:bg-teal/90 disabled:opacity-40"
        >
          {saving ? 'Zapisywanie...' : 'Zapisz regułę'}
        </button>
        <button
          onClick={() => setOpen(false)}
          className="px-4 py-2 text-mgray text-sm border border-blue/30 rounded-lg hover:bg-blue/10"
        >
          Anuluj
        </button>
      </div>
    </div>
  );
}

// ── Karta pojedynczej polityki ────────────────────────────────────────────────

function PolicyCard({ policy, onChanged }: { policy: Policy; onChanged: () => void }) {
  const [keywords, setKeywords] = useState<string[]>(policy.condition_json?.keywords ?? []);
  const [newKw, setNewKw] = useState('');
  const [saving, setSaving] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [dirty, setDirty] = useState(false);

  function addKeyword() {
    const kw = newKw.trim();
    if (!kw || keywords.includes(kw)) return;
    setKeywords(prev => [...prev, kw]);
    setNewKw('');
    setDirty(true);
  }

  function removeKeyword(kw: string) {
    setKeywords(prev => prev.filter(k => k !== kw));
    setDirty(true);
  }

  async function saveKeywords() {
    setSaving(true);
    try {
      await api.policies.updateKeywords(policy.id, keywords);
      setDirty(false);
      onChanged();
    } catch (e) {
      alert(String(e));
    } finally {
      setSaving(false);
    }
  }

  async function toggle() {
    setToggling(true);
    try {
      await api.policies.toggle(policy.id);
      onChanged();
    } catch (e) {
      alert(String(e));
    } finally {
      setToggling(false);
    }
  }

  return (
    <div className={`border rounded-xl overflow-hidden transition-opacity ${!policy.active ? 'opacity-50' : ''}`}
         style={{ borderColor: policy.active ? 'rgb(30 111 191 / 0.4)' : 'rgb(100 116 139 / 0.3)' }}>
      {/* Header */}
      <div className="px-5 py-3 bg-dark/40 flex items-center gap-3 flex-wrap">
        <button
          onClick={toggle}
          disabled={toggling}
          className={`relative w-10 h-5 rounded-full transition-colors flex-shrink-0 ${
            policy.active ? 'bg-teal' : 'bg-mgray/30'
          }`}
          title={policy.active ? 'Dezaktywuj' : 'Aktywuj'}
        >
          <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform ${
            policy.active ? 'translate-x-5' : 'translate-x-0.5'
          }`} />
        </button>
        {policy.policy_code && (
          <span className="font-mono text-xs font-bold px-2 py-0.5 rounded bg-blue/20 text-blue-300 border border-blue/30">
            {policy.policy_code}
          </span>
        )}
        <span className="font-semibold text-white text-sm">{policy.name}</span>
        <span className="ml-auto text-xs text-mgray/60">
          Priorytet: {policy.priority} · Zasięg: {policy.level} · v{policy.version}
        </span>
        {!policy.active && (
          <span className="text-xs text-mgray bg-mgray/10 px-2 py-0.5 rounded border border-mgray/20">
            NIEAKTYWNA
          </span>
        )}
      </div>

      {/* Komunikat blokady */}
      {policy.action_json?.reason && (
        <div className="px-5 py-2 border-b border-blue/10 text-xs text-mgray/70 italic">
          Komunikat: „{policy.action_json.reason}"
        </div>
      )}

      {/* Słowa kluczowe */}
      <div className="px-5 py-4">
        <div className="text-xs text-mgray mb-2 font-semibold uppercase tracking-wide">
          Słowa kluczowe ({keywords.length})
        </div>
        <div className="flex flex-wrap gap-2 mb-3 min-h-[2rem]">
          {keywords.map(kw => (
            <span
              key={kw}
              className="flex items-center gap-1.5 text-xs bg-red-900/20 border border-red-800/40 text-red-300 px-2 py-1 rounded-lg font-mono"
            >
              {kw}
              <button
                onClick={() => removeKeyword(kw)}
                className="text-red-400/60 hover:text-red-300 transition-colors leading-none"
              >
                ×
              </button>
            </span>
          ))}
          {keywords.length === 0 && (
            <span className="text-xs text-mgray/40 italic">Brak słów kluczowych — reguła nigdy nie aktywuje.</span>
          )}
        </div>

        {/* Dodawanie słowa */}
        <div className="flex gap-2">
          <input
            className="flex-1 bg-dark border border-blue/30 rounded-lg px-3 py-1.5 text-sm text-white font-mono focus:outline-none focus:border-teal"
            placeholder="Dodaj słowo kluczowe..."
            value={newKw}
            onChange={e => setNewKw(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addKeyword()}
          />
          <button
            onClick={addKeyword}
            disabled={!newKw.trim()}
            className="px-3 py-1.5 bg-blue/20 border border-blue/30 text-blue-300 text-sm rounded-lg hover:bg-blue/30 disabled:opacity-40"
          >
            + Dodaj
          </button>
          {dirty && (
            <button
              onClick={saveKeywords}
              disabled={saving}
              className="px-4 py-1.5 bg-teal text-dark text-sm font-semibold rounded-lg hover:bg-teal/90 disabled:opacity-40"
            >
              {saving ? '...' : '✓ Zapisz'}
            </button>
          )}
        </div>
        {dirty && (
          <p className="text-xs text-yellow-400 mt-2">
            Niezapisane zmiany · Gateway zastosuje je w ciągu 60s.
          </p>
        )}
      </div>
    </div>
  );
}

// ── Formularz nowego wymagania AI Act ─────────────────────────────────────────

function NewRequirementForm({ onSaved }: { onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    risk_level: 'high' as RiskLevel,
    article_ref: '',
    requirement_title: '',
    requirement_text: '',
    sort_order: '100',
    default_severity: 'major' as 'critical' | 'major' | 'minor',
    default_deadline_days: '30',
    decl_key: '',
  });

  async function save() {
    if (!form.article_ref || !form.requirement_title || !form.requirement_text) return;
    setSaving(true);
    try {
      await api.compliance.create({
        ...form,
        sort_order: parseInt(form.sort_order) || 100,
        default_deadline_days: parseInt(form.default_deadline_days) || 30,
        decl_key: form.decl_key.trim() || null,
      });
      setOpen(false);
      setForm({
        risk_level: 'high', article_ref: '', requirement_title: '', requirement_text: '',
        sort_order: '100', default_severity: 'major', default_deadline_days: '30', decl_key: '',
      });
      onSaved();
    } catch (e) {
      alert(String(e));
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="mt-3 px-4 py-2 border border-dashed border-blue/40 text-teal text-sm rounded-lg hover:border-teal/60 hover:bg-teal/5 transition-colors w-full"
      >
        + Dodaj wymaganie
      </button>
    );
  }

  return (
    <div className="mt-3 bg-dark/60 border border-blue/30 rounded-xl p-4 space-y-3">
      <div className="font-semibold text-white text-sm">Nowe wymaganie EU AI Act</div>
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="text-xs text-mgray mb-1 block">Poziom ryzyka *</label>
          <select
            className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal"
            value={form.risk_level}
            onChange={e => setForm(f => ({ ...f, risk_level: e.target.value as RiskLevel }))}
          >
            {RISK_ORDER.map(r => (
              <option key={r} value={r}>{RISK_LABEL[r]}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-mgray mb-1 block">Artykuł *</label>
          <input
            className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal"
            placeholder="np. Art. 9 ust. 2"
            value={form.article_ref}
            onChange={e => setForm(f => ({ ...f, article_ref: e.target.value }))}
          />
        </div>
        <div>
          <label className="text-xs text-mgray mb-1 block">Kolejność</label>
          <input
            type="number"
            className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal"
            value={form.sort_order}
            onChange={e => setForm(f => ({ ...f, sort_order: e.target.value }))}
          />
        </div>
      </div>
      <div>
        <label className="text-xs text-mgray mb-1 block">Tytuł wymagania *</label>
        <input
          className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal"
          placeholder="np. Rejestr systemów AI wysokiego ryzyka"
          value={form.requirement_title}
          onChange={e => setForm(f => ({ ...f, requirement_title: e.target.value }))}
        />
      </div>
      <div>
        <label className="text-xs text-mgray mb-1 block">Opis wymagania *</label>
        <textarea
          rows={3}
          className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal resize-none"
          placeholder="Szczegółowy opis wymagania i sposobu jego spełnienia..."
          value={form.requirement_text}
          onChange={e => setForm(f => ({ ...f, requirement_text: e.target.value }))}
        />
      </div>
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="text-xs text-mgray mb-1 block">Waga domyślna</label>
          <select
            className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal"
            value={form.default_severity}
            onChange={e => setForm(f => ({ ...f, default_severity: e.target.value as typeof f.default_severity }))}
          >
            <option value="critical">Krytyczna</option>
            <option value="major">Poważna</option>
            <option value="minor">Drobna</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-mgray mb-1 block">Termin (dni)</label>
          <input
            type="number"
            className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal"
            value={form.default_deadline_days}
            onChange={e => setForm(f => ({ ...f, default_deadline_days: e.target.value }))}
          />
        </div>
        <div>
          <label className="text-xs text-mgray mb-1 block">Klucz samo-deklaracji</label>
          <input
            className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal font-mono"
            placeholder="np. art9_risk_management"
            value={form.decl_key}
            onChange={e => setForm(f => ({ ...f, decl_key: e.target.value }))}
          />
        </div>
      </div>
      <p className="text-[11px] text-mgray/50 -mt-1">
        Klucz samo-deklaracji łączy to wymaganie z polem w zakładce Rejestr agenta.
        Puste = wymaganie nie do samo-zadeklarowania (np. zakaz z art. 5).
      </p>
      <div className="flex gap-3">
        <button
          onClick={save}
          disabled={saving || !form.article_ref || !form.requirement_title || !form.requirement_text}
          className="px-4 py-2 bg-teal text-dark text-sm font-semibold rounded-lg hover:bg-teal/90 disabled:opacity-40"
        >
          {saving ? 'Zapisywanie...' : 'Zapisz wymaganie'}
        </button>
        <button onClick={() => setOpen(false)} className="px-4 py-2 text-mgray text-sm border border-blue/30 rounded-lg hover:bg-blue/10">
          Anuluj
        </button>
      </div>
    </div>
  );
}

// ── Wiersz wymagania ──────────────────────────────────────────────────────────

function RequirementRow({ req, onChanged }: { req: AiActRequirement; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    article_ref:            req.article_ref,
    requirement_title:      req.requirement_title,
    requirement_text:       req.requirement_text,
    default_severity:       req.default_severity,
    default_deadline_days:  String(req.default_deadline_days),
    decl_key:               req.decl_key ?? '',
  });

  async function save() {
    setSaving(true);
    try {
      await api.compliance.update(req.id, {
        ...form,
        default_deadline_days: parseInt(form.default_deadline_days) || 0,
        decl_key: form.decl_key.trim() || null,
      });
      setEditing(false);
      onChanged();
    } catch (e) {
      alert(String(e));
    } finally {
      setSaving(false);
    }
  }

  async function toggle() {
    try {
      await api.compliance.update(req.id, { active: !req.active });
      onChanged();
    } catch (e) {
      alert(String(e));
    }
  }

  async function remove() {
    if (!confirm(`Usunąć wymaganie "${req.requirement_title}"?`)) return;
    try {
      await api.compliance.delete(req.id);
      onChanged();
    } catch (e) {
      alert(String(e));
    }
  }

  if (editing) {
    return (
      <div className="px-4 py-3 bg-dark/40 space-y-2 border-b border-blue/10">
        <div className="grid grid-cols-2 gap-3">
          <input
            className="bg-navy border border-blue/30 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-teal"
            value={form.article_ref}
            onChange={e => setForm(f => ({ ...f, article_ref: e.target.value }))}
            placeholder="Artykuł"
          />
          <input
            className="bg-navy border border-blue/30 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-teal"
            value={form.requirement_title}
            onChange={e => setForm(f => ({ ...f, requirement_title: e.target.value }))}
            placeholder="Tytuł"
          />
        </div>
        <textarea
          rows={2}
          className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-teal resize-none"
          value={form.requirement_text}
          onChange={e => setForm(f => ({ ...f, requirement_text: e.target.value }))}
        />
        <div className="grid grid-cols-3 gap-3">
          <select
            className="bg-navy border border-blue/30 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-teal"
            value={form.default_severity}
            onChange={e => setForm(f => ({ ...f, default_severity: e.target.value as typeof f.default_severity }))}
          >
            <option value="critical">Krytyczna</option>
            <option value="major">Poważna</option>
            <option value="minor">Drobna</option>
          </select>
          <input
            type="number"
            className="bg-navy border border-blue/30 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-teal"
            value={form.default_deadline_days}
            onChange={e => setForm(f => ({ ...f, default_deadline_days: e.target.value }))}
            placeholder="Termin (dni)"
          />
          <input
            className="bg-navy border border-blue/30 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-teal font-mono"
            value={form.decl_key}
            onChange={e => setForm(f => ({ ...f, decl_key: e.target.value }))}
            placeholder="Klucz samo-deklaracji"
          />
        </div>
        <div className="flex gap-2">
          <button onClick={save} disabled={saving}
            className="px-3 py-1 bg-teal text-dark text-xs font-semibold rounded-lg disabled:opacity-40">
            {saving ? '...' : '✓ Zapisz'}
          </button>
          <button onClick={() => setEditing(false)} className="px-3 py-1 text-xs text-mgray border border-blue/20 rounded-lg">
            Anuluj
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={`px-4 py-3 border-b border-blue/10 flex items-start gap-3 hover:bg-blue/5 transition-colors ${!req.active ? 'opacity-40' : ''}`}>
      <button onClick={toggle} className={`mt-0.5 w-8 h-4 rounded-full flex-shrink-0 transition-colors ${req.active ? 'bg-teal' : 'bg-mgray/30'}`}>
        <span className={`block w-3 h-3 bg-white rounded-full mt-0.5 transition-transform ${req.active ? 'translate-x-4' : 'translate-x-0.5'}`} />
      </button>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="text-xs font-mono font-bold text-teal">{req.article_ref}</span>
          <span className="text-sm font-semibold text-white">{req.requirement_title}</span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded ${SEVERITY_BADGE[req.default_severity]}`}>
            {SEVERITY_LABEL[req.default_severity]}
          </span>
          <span className="text-[10px] text-mgray/50">{req.default_deadline_days} dni</span>
          {req.decl_key ? (
            <span className="text-[10px] font-mono text-mgray/40">{req.decl_key}</span>
          ) : (
            <span className="text-[10px] text-orange-400/70">brak samo-deklaracji</span>
          )}
        </div>
        <p className="text-xs text-mgray mt-0.5 leading-relaxed">{req.requirement_text}</p>
      </div>
      <div className="flex gap-2 flex-shrink-0">
        <button onClick={() => setEditing(true)} className="text-xs text-mgray hover:text-white border border-blue/20 px-2 py-1 rounded transition-colors">
          Edytuj
        </button>
        <button onClick={remove} className="text-xs text-red-400/60 hover:text-red-300 border border-red-900/30 px-2 py-1 rounded transition-colors">
          Usuń
        </button>
      </div>
    </div>
  );
}

// ── Strona główna ─────────────────────────────────────────────────────────────

export default function PoliciesPage() {
  const [tab, setTab] = useState<Tab>('rules');
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [requirements, setRequirements] = useState<AiActRequirement[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');

  async function load() {
    setLoading(true);
    try {
      const [p, r] = await Promise.all([api.policies.list(), api.compliance.list()]);
      setPolicies(p);
      setRequirements(r);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  const visiblePolicies = useMemo(() => policies.filter(p => matchesQuery(
    [p.name, p.policy_code, p.rule_type, p.level, p.action_json?.reason,
     ...(p.condition_json?.keywords ?? [])],
    query,
  )), [policies, query]);

  const reqByRisk = RISK_ORDER.reduce<Record<RiskLevel, AiActRequirement[]>>(
    (acc, level) => {
      acc[level] = requirements.filter(r => r.risk_level === level);
      return acc;
    },
    { unacceptable: [], high: [], limited: [], minimal: [] },
  );

  return (
    <div className="space-y-6">
      {/* Nagłówek */}
      <div>
        <h1 className="text-2xl font-bold text-white">Polityki i Compliance</h1>
        <p className="text-mgray text-sm mt-1">
          Zarządzaj regułami bezpieczeństwa i wymaganiami EU AI Act bez zmian w kodzie.
          Zmiany reguł aktywne w Gateway w ciągu 60s.
        </p>
      </div>

      {/* Banner */}
      <div className="bg-navy border border-teal/20 rounded-lg px-5 py-3 flex items-center gap-3 text-sm">
        <span className="text-teal text-lg">⚙</span>
        <div>
          <span className="text-white font-medium">Konfiguracja bez restartu:</span>
          <span className="text-mgray ml-2">
            Gateway odświeża reguły z bazy co 60 sekund automatycznie.
            Po zapisaniu zmiany — nic więcej nie trzeba robić.
          </span>
        </div>
      </div>

      {/* Zakładki */}
      <div className="flex gap-1 border-b border-blue/20">
        {([['rules', 'Reguły Bezpieczeństwa'], ['aiact', 'Wymagania EU AI Act']] as const).map(([id, label]) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`px-5 py-2.5 text-sm font-semibold border-b-2 transition-colors ${
              tab === id
                ? 'border-teal text-teal'
                : 'border-transparent text-mgray hover:text-white'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="text-mgray animate-pulse py-8">Ładowanie...</div>
      ) : tab === 'rules' ? (

        /* ── TAB: Reguły ── */
        <div className="space-y-4">
          <p className="text-xs text-mgray">
            Reguły blokujące sprawdzane są w kolejności priorytetu (niższy numer = wyższy priorytet).
            Pierwsze dopasowanie słowa kluczowego aktywuje blokadę przed wywołaniem modelu.
          </p>

          {policies.length > 0 && (
            <SearchBox
              value={query}
              onChange={setQuery}
              placeholder="Szukaj reguły — nazwa, kod, słowo kluczowe, powód..."
              count={visiblePolicies.length}
              total={policies.length}
            />
          )}

          {policies.length === 0 && (
            <div className="text-center py-10 text-mgray/50">Brak zdefiniowanych reguł.</div>
          )}

          {policies.length > 0 && visiblePolicies.length === 0 && (
            <div className="text-center py-10 text-mgray/50">Brak reguł pasujących do „{query}”.</div>
          )}

          {visiblePolicies.map(p => (
            <PolicyCard key={p.id} policy={p} onChanged={load} />
          ))}

          <NewPolicyForm onSaved={load} />
        </div>

      ) : (

        /* ── TAB: EU AI Act ── */
        <div className="space-y-6">
          <p className="text-xs text-mgray">
            Wymagania przypisane do poziomów ryzyka. Widoczne w raportach PDF i widoku zgodności agenta.
            Możesz dodawać własne adnotacje do konkretnych artykułów EU AI Act.
          </p>

          {RISK_ORDER.map(level => (
            <div key={level} className="bg-navy border border-blue/30 rounded-xl overflow-hidden">
              <div className={`px-5 py-3 border-b border-blue/20 flex items-center gap-3 ${RISK_STYLE[level].split(' ')[2]}`}>
                <span className={`text-xs font-bold px-2 py-0.5 rounded border ${RISK_STYLE[level]}`}>
                  {RISK_LABEL[level].toUpperCase()}
                </span>
                <span className="text-white text-sm font-semibold">
                  {reqByRisk[level].length} {reqByRisk[level].length === 1 ? 'wymaganie' : 'wymagań'}
                </span>
              </div>

              <div>
                {reqByRisk[level].length === 0 ? (
                  <div className="px-5 py-4 text-xs text-mgray/40 italic">Brak wymagań dla tego poziomu.</div>
                ) : (
                  reqByRisk[level].map(r => (
                    <RequirementRow key={r.id} req={r} onChanged={load} />
                  ))
                )}
              </div>

              <div className="px-4 py-3">
                <NewRequirementForm onSaved={load} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
