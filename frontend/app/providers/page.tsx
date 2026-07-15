'use client';

import { useEffect, useMemo, useState } from 'react';
import { api, Provider, DataSensitivityLevel, ProviderType } from '@/lib/api';
import SearchBox from '@/components/SearchBox';
import { matchesQuery } from '@/lib/search';

// ── Stałe ─────────────────────────────────────────────────────────────────────

const SENSITIVITY_ORDER: DataSensitivityLevel[] = ['public', 'internal', 'confidential', 'privileged'];

const SENSITIVITY_LABEL: Record<DataSensitivityLevel, string> = {
  public:       'Publiczny',
  internal:     'Wewnętrzny',
  confidential: 'Poufny',
  privileged:   'Uprzywilejowany',
};

const SENSITIVITY_STYLE: Record<DataSensitivityLevel, string> = {
  public:       'text-green-400 border-green-800 bg-green-900/20',
  internal:     'text-blue-300 border-blue-800 bg-blue-900/20',
  confidential: 'text-orange-300 border-orange-800 bg-orange-900/20',
  privileged:   'text-purple-300 border-purple-800 bg-purple-900/20',
};

const PROVIDER_TYPES: ProviderType[] = ['anthropic', 'openai', 'deepseek', 'google', 'ollama', 'vllm', 'bielik', 'custom'];

const TYPE_ICON: Record<string, string> = {
  anthropic: '◈',
  openai:    '◇',
  deepseek:  '◆',
  google:    '◉',
  ollama:    '⬡',
  vllm:      '⬢',
  bielik:    '⊛',
  custom:    '◎',
};

const TYPE_LABEL: Record<string, string> = {
  anthropic: 'Anthropic',
  openai:    'OpenAI',
  deepseek:  'DeepSeek',
  google:    'Google',
  ollama:    'Ollama (on-prem)',
  vllm:      'vLLM (on-prem)',
  bielik:    'Bielik (on-prem)',
  custom:    'Custom / inny',
};

// ── Formularz dodawania providera ─────────────────────────────────────────────

const EMPTY_FORM = {
  name: '',
  provider_type: 'anthropic' as ProviderType,
  model_ids: '',
  base_url: '',
  api_key_env: '',
  max_data_sensitivity: 'internal' as DataSensitivityLevel,
  priority: '10',
  notes: '',
};

function AddProviderForm({ onSaved }: { onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);

  function f(key: keyof typeof EMPTY_FORM, val: string) {
    setForm(prev => ({ ...prev, [key]: val }));
  }

  async function save() {
    if (!form.name || !form.provider_type) return;
    setSaving(true);
    try {
      await api.providers.create({
        name:                 form.name,
        provider_type:        form.provider_type,
        model_ids:            form.model_ids.split('\n').map(s => s.trim()).filter(Boolean),
        base_url:             form.base_url || null,
        api_key_env:          form.api_key_env || null,
        max_data_sensitivity: form.max_data_sensitivity,
        priority:             parseInt(form.priority) || 10,
        notes:                form.notes || null,
      });
      setOpen(false);
      setForm(EMPTY_FORM);
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
        className="px-4 py-2 border border-dashed border-blue/40 text-teal text-sm rounded-lg hover:border-teal/60 hover:bg-teal/5 transition-colors"
      >
        + Dodaj providera
      </button>
    );
  }

  const needsUrl = ['ollama', 'vllm', 'custom'].includes(form.provider_type);

  return (
    <div className="bg-dark/60 border border-blue/30 rounded-xl p-5 space-y-4">
      <div className="font-semibold text-white text-sm">Nowy provider LLM</div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-xs text-mgray mb-1 block">Nazwa *</label>
          <input
            className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal"
            placeholder="np. Anthropic Claude (Cloud)"
            value={form.name}
            onChange={e => f('name', e.target.value)}
          />
        </div>
        <div>
          <label className="text-xs text-mgray mb-1 block">Typ *</label>
          <select
            className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal"
            value={form.provider_type}
            onChange={e => f('provider_type', e.target.value as ProviderType)}
          >
            {PROVIDER_TYPES.map(t => (
              <option key={t} value={t}>{TYPE_ICON[t]} {TYPE_LABEL[t]}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-xs text-mgray mb-1 block">Max wrażliwość danych *</label>
          <select
            className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal"
            value={form.max_data_sensitivity}
            onChange={e => f('max_data_sensitivity', e.target.value as DataSensitivityLevel)}
          >
            {SENSITIVITY_ORDER.map(s => (
              <option key={s} value={s}>{SENSITIVITY_LABEL[s]}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-mgray mb-1 block">Priorytet (niższy = preferowany)</label>
          <input
            type="number"
            className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal"
            value={form.priority}
            onChange={e => f('priority', e.target.value)}
          />
        </div>
      </div>

      <div>
        <label className="text-xs text-mgray mb-1 block">Obsługiwane modele (jeden na linię) *</label>
        <textarea
          rows={3}
          className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-teal resize-none"
          placeholder={"claude-sonnet-4-6\nclaude-haiku-4-5-20251001"}
          value={form.model_ids}
          onChange={e => f('model_ids', e.target.value)}
        />
      </div>

      {needsUrl && (
        <div>
          <label className="text-xs text-mgray mb-1 block">Base URL *</label>
          <input
            className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-teal"
            placeholder="http://ollama:11434"
            value={form.base_url}
            onChange={e => f('base_url', e.target.value)}
          />
        </div>
      )}

      <div>
        <label className="text-xs text-mgray mb-1 block">Zmienna środowiskowa z kluczem API</label>
        <input
          className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-teal"
          placeholder="ANTHROPIC_API_KEY"
          value={form.api_key_env}
          onChange={e => f('api_key_env', e.target.value)}
        />
        <p className="text-xs text-mgray/50 mt-1">
          Nazwa zmiennej w `.env` kontenera Gateway. Klucz nigdy nie opuszcza serwera.
        </p>
      </div>

      <div>
        <label className="text-xs text-mgray mb-1 block">Notatka / zastrzeżenia prawne</label>
        <textarea
          rows={2}
          className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal resize-none"
          placeholder="np. Wymaga DPA. Nie używać dla danych objętych tajemnicą adwokacką."
          value={form.notes}
          onChange={e => f('notes', e.target.value)}
        />
      </div>

      <div className="flex gap-3">
        <button
          onClick={save}
          disabled={saving || !form.name || !form.model_ids.trim()}
          className="px-4 py-2 bg-teal text-dark text-sm font-semibold rounded-lg hover:bg-teal/90 disabled:opacity-40"
        >
          {saving ? 'Zapisywanie...' : 'Zapisz providera'}
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

// ── Karta providera ───────────────────────────────────────────────────────────

function ProviderCard({ provider, onChanged }: { provider: Provider; onChanged: () => void }) {
  const [toggling, setToggling] = useState(false);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [form, setForm] = useState({
    name:                 provider.name,
    model_ids:            provider.model_ids.join('\n'),
    base_url:             provider.base_url ?? '',
    api_key_env:          provider.api_key_env ?? '',
    max_data_sensitivity: provider.max_data_sensitivity,
    priority:             String(provider.priority),
    notes:                provider.notes ?? '',
  });

  function f(key: keyof typeof form, val: string) {
    setForm(prev => ({ ...prev, [key]: val }));
  }

  async function toggleActive() {
    setToggling(true);
    try {
      await api.providers.update(provider.id, { active: !provider.active });
      onChanged();
    } catch (e) {
      alert(String(e));
    } finally {
      setToggling(false);
    }
  }

  async function toggleHealth() {
    try {
      await api.providers.setHealth(provider.id, !provider.is_healthy);
      onChanged();
    } catch (e) {
      alert(String(e));
    }
  }

  async function saveEdit() {
    setSaving(true);
    try {
      await api.providers.update(provider.id, {
        name:                 form.name,
        model_ids:            form.model_ids.split('\n').map(s => s.trim()).filter(Boolean),
        base_url:             form.base_url || null,
        api_key_env:          form.api_key_env || null,
        max_data_sensitivity: form.max_data_sensitivity as DataSensitivityLevel,
        priority:             parseInt(form.priority) || 10,
        notes:                form.notes || null,
      });
      setEditing(false);
      onChanged();
    } catch (e) {
      alert(String(e));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!confirm(`Usunąć providera "${provider.name}"?\n\nTa operacja jest nieodwracalna.`)) return;
    setDeleting(true);
    try {
      await api.providers.delete(provider.id);
      onChanged();
    } catch (e) {
      alert(String(e));
      setDeleting(false);
    }
  }

  const sensitivityStyle = SENSITIVITY_STYLE[provider.max_data_sensitivity];

  return (
    <div className={`border rounded-xl overflow-hidden transition-opacity ${!provider.active ? 'opacity-50' : ''}`}
         style={{ borderColor: provider.active ? 'rgb(30 111 191 / 0.4)' : 'rgb(100 116 139 / 0.3)' }}>

      {/* Header */}
      <div className="px-5 py-3 bg-dark/40 flex items-center gap-3 flex-wrap">
        {/* Toggle active */}
        <button
          onClick={toggleActive}
          disabled={toggling}
          className={`relative w-10 h-5 rounded-full transition-colors flex-shrink-0 ${
            provider.active ? 'bg-teal' : 'bg-mgray/30'
          }`}
          title={provider.active ? 'Dezaktywuj' : 'Aktywuj'}
        >
          <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform ${
            provider.active ? 'translate-x-5' : 'translate-x-0.5'
          }`} />
        </button>

        {/* Type icon + name */}
        <span className="text-lg" title={TYPE_LABEL[provider.provider_type]}>
          {TYPE_ICON[provider.provider_type] ?? '◎'}
        </span>
        <span className="font-semibold text-white text-sm">{provider.name}</span>

        {/* Sensitivity badge */}
        <span className={`text-xs font-bold px-2 py-0.5 rounded border ${sensitivityStyle}`}>
          {SENSITIVITY_LABEL[provider.max_data_sensitivity]}
        </span>

        {/* Health */}
        <button
          onClick={toggleHealth}
          title={provider.is_healthy ? 'Zdrowy — kliknij aby oznaczyć jako niezdrowy' : 'Niezdrowy — kliknij aby oznaczyć jako zdrowy'}
          className={`text-xs px-2 py-0.5 rounded border transition-colors ${
            provider.is_healthy
              ? 'text-green-400 border-green-800 bg-green-900/20 hover:bg-green-900/40'
              : 'text-red-400 border-red-800 bg-red-900/20 hover:bg-red-900/40'
          }`}
        >
          {provider.is_healthy ? '● Zdrowy' : '✖ Niezdrowy'}
        </button>

        <span className="ml-auto text-xs text-mgray/50">
          Priorytet: {provider.priority} · {TYPE_LABEL[provider.provider_type]}
        </span>
      </div>

      {/* Body */}
      {editing ? (
        <div className="px-5 py-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-mgray mb-1 block">Nazwa</label>
              <input
                className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-teal"
                value={form.name}
                onChange={e => f('name', e.target.value)}
              />
            </div>
            <div>
              <label className="text-xs text-mgray mb-1 block">Max wrażliwość</label>
              <select
                className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-teal"
                value={form.max_data_sensitivity}
                onChange={e => f('max_data_sensitivity', e.target.value)}
              >
                {SENSITIVITY_ORDER.map(s => (
                  <option key={s} value={s}>{SENSITIVITY_LABEL[s]}</option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <label className="text-xs text-mgray mb-1 block">Modele (jeden na linię)</label>
            <textarea
              rows={3}
              className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-1.5 text-sm text-white font-mono focus:outline-none focus:border-teal resize-none"
              value={form.model_ids}
              onChange={e => f('model_ids', e.target.value)}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-mgray mb-1 block">Base URL</label>
              <input
                className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-1.5 text-sm text-white font-mono focus:outline-none focus:border-teal"
                value={form.base_url}
                onChange={e => f('base_url', e.target.value)}
              />
            </div>
            <div>
              <label className="text-xs text-mgray mb-1 block">Zmienna klucza API</label>
              <input
                className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-1.5 text-sm text-white font-mono focus:outline-none focus:border-teal"
                value={form.api_key_env}
                onChange={e => f('api_key_env', e.target.value)}
              />
            </div>
          </div>
          <div className="grid grid-cols-4 gap-3">
            <div>
              <label className="text-xs text-mgray mb-1 block">Priorytet</label>
              <input
                type="number"
                className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-teal"
                value={form.priority}
                onChange={e => f('priority', e.target.value)}
              />
            </div>
            <div className="col-span-3">
              <label className="text-xs text-mgray mb-1 block">Notatki</label>
              <input
                className="w-full bg-navy border border-blue/30 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-teal"
                value={form.notes}
                onChange={e => f('notes', e.target.value)}
              />
            </div>
          </div>
          <div className="flex gap-2">
            <button onClick={saveEdit} disabled={saving}
              className="px-3 py-1.5 bg-teal text-dark text-sm font-semibold rounded-lg disabled:opacity-40">
              {saving ? '...' : '✓ Zapisz'}
            </button>
            <button onClick={() => setEditing(false)} className="px-3 py-1.5 text-mgray text-sm border border-blue/20 rounded-lg">
              Anuluj
            </button>
          </div>
        </div>
      ) : (
        <div className="px-5 py-4 space-y-2">
          {/* Model IDs */}
          <div>
            <div className="text-xs text-mgray mb-1.5 font-semibold uppercase tracking-wide">
              Obsługiwane modele
            </div>
            <div className="flex flex-wrap gap-1.5">
              {provider.model_ids.map(m => (
                <span key={m} className="text-xs font-mono bg-blue/10 border border-blue/20 text-blue-200 px-2 py-0.5 rounded">
                  {m}
                </span>
              ))}
              {provider.model_ids.length === 0 && (
                <span className="text-xs text-mgray/40 italic">Brak zdefiniowanych modeli</span>
              )}
            </div>
          </div>

          {/* Connection info */}
          <div className="flex gap-4 text-xs text-mgray/60">
            {provider.base_url && (
              <span>URL: <code className="text-blue-300">{provider.base_url}</code></span>
            )}
            {provider.api_key_env && (
              <span>Klucz: <code className="text-teal/70">${provider.api_key_env}</code></span>
            )}
            {provider.last_health_check_at && (
              <span>Ostatni check: {new Date(provider.last_health_check_at).toLocaleDateString('pl-PL')}</span>
            )}
          </div>

          {/* Notes */}
          {provider.notes && (
            <p className="text-xs text-mgray/60 italic border-l-2 border-blue/20 pl-3">
              {provider.notes}
            </p>
          )}

          {/* Actions */}
          <div className="flex gap-2 pt-1">
            <button onClick={() => setEditing(true)}
              className="text-xs text-mgray hover:text-white border border-blue/20 px-3 py-1 rounded transition-colors">
              Edytuj
            </button>
            <button onClick={remove} disabled={deleting}
              className="text-xs text-red-400/60 hover:text-red-300 border border-red-900/30 px-3 py-1 rounded transition-colors disabled:opacity-40">
              {deleting ? '...' : 'Usuń'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Strona główna ─────────────────────────────────────────────────────────────

export default function ProvidersPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');

  async function load() {
    setLoading(true);
    try {
      setProviders(await api.providers.list());
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  const visible = useMemo(() => providers.filter(p => matchesQuery(
    [p.name, p.provider_type, p.base_url, p.max_data_sensitivity, p.notes, ...(p.model_ids ?? [])],
    query,
  )), [providers, query]);

  const byLevel: Record<DataSensitivityLevel, Provider[]> = {
    privileged:   visible.filter(p => p.max_data_sensitivity === 'privileged'),
    confidential: visible.filter(p => p.max_data_sensitivity === 'confidential'),
    internal:     visible.filter(p => p.max_data_sensitivity === 'internal'),
    public:       visible.filter(p => p.max_data_sensitivity === 'public'),
  };

  const activeCount  = providers.filter(p => p.active).length;
  const healthyCount = providers.filter(p => p.active && p.is_healthy).length;

  return (
    <div className="space-y-6">
      {/* Nagłówek */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Providerzy LLM</h1>
          <p className="text-mgray text-sm mt-1">
            Zarządzaj dostawcami modeli językowych. Gateway automatycznie wybiera
            providera o wymaganym poziomie ochrony danych.
          </p>
        </div>
        <div className="flex gap-3 text-xs text-right flex-shrink-0">
          <div className="bg-dark border border-blue/20 rounded-lg px-3 py-2">
            <div className="text-white font-bold text-lg">{activeCount}</div>
            <div className="text-mgray">aktywnych</div>
          </div>
          <div className="bg-dark border border-green-900/30 rounded-lg px-3 py-2">
            <div className="text-green-400 font-bold text-lg">{healthyCount}</div>
            <div className="text-mgray">zdrowych</div>
          </div>
        </div>
      </div>

      {/* Banner — routing logic */}
      <div className="bg-navy border border-purple-900/30 rounded-lg px-5 py-3 text-xs text-mgray/80 leading-relaxed">
        <span className="text-purple-300 font-semibold">Logika routingu: </span>
        Każde wywołanie agenta jest klasyfikowane pod kątem wrażliwości danych
        (public → internal → confidential → privileged).
        Gateway wybiera aktywnego, zdrowego providera z&nbsp;najniższym priorytetem,
        który obsługuje wymagany poziom lub wyższy.
        Dane uprzywilejowane (tajemnica adwokacka) kierowane są wyłącznie do providerów on-prem.
      </div>

      {/* Formularz dodawania */}
      <AddProviderForm onSaved={load} />

      {/* Wyszukiwarka */}
      {providers.length > 0 && (
        <div className="flex items-center gap-3">
          <SearchBox
            value={query}
            onChange={setQuery}
            placeholder="Szukaj providera — nazwa, typ, model, base_url..."
            count={visible.length}
            total={providers.length}
          />
        </div>
      )}

      {loading ? (
        <div className="text-mgray animate-pulse py-8">Ładowanie providerów...</div>
      ) : providers.length === 0 ? (
        <div className="text-center py-12 text-mgray/40">
          Brak zdefiniowanych providerów. Dodaj pierwszego powyżej.
        </div>
      ) : visible.length === 0 ? (
        <div className="text-center py-12 text-mgray/50">
          Brak providerów pasujących do „{query}”.
        </div>
      ) : (
        /* Grupowanie wg max_data_sensitivity */
        <div className="space-y-8">
          {SENSITIVITY_ORDER.slice().reverse().map(level => {
            const group = byLevel[level];
            if (group.length === 0) return null;
            const style = SENSITIVITY_STYLE[level];
            return (
              <div key={level}>
                <div className="flex items-center gap-3 mb-3">
                  <span className={`text-xs font-bold px-2 py-1 rounded border ${style}`}>
                    {SENSITIVITY_LABEL[level].toUpperCase()}
                  </span>
                  <div className="h-px flex-1 bg-blue/10" />
                  <span className="text-xs text-mgray/50">{group.length} provider{group.length !== 1 ? 'ów' : ''}</span>
                </div>
                <div className="space-y-3">
                  {group.map(p => (
                    <ProviderCard key={p.id} provider={p} onChanged={load} />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
