'use client';

import { useEffect, useState } from 'react';
import { api, Setting } from '@/lib/api';
import { useAuth } from '@/components/AuthProvider';

const CATEGORY_ORDER = [
  'pricing', 'budget', 'oversight', 'intervals',
  'models', 'security', 'pagination', 'compliance',
];

const CATEGORY_META: Record<string, { title: string; desc: string }> = {
  pricing:    { title: 'Cennik i koszty',        desc: 'Stawki modeli i przelicznik walutowy używane do wyceny wywołań.' },
  budget:     { title: 'Budżety',                desc: 'Domyślne limity i progi alertów kosztowych dla nowych agentów.' },
  oversight:  { title: 'Nadzór',                 desc: 'Progi i limity kolejki nadzoru człowieka (art. 14 EU AI Act).' },
  intervals:  { title: 'Interwały',              desc: 'Częstotliwość zadań tła (odświeżanie polityk, monitor TTL).' },
  models:     { title: 'Modele domyślne',        desc: 'Domyślne modele i parametry wywołań LLM.' },
  security:   { title: 'Bezpieczeństwo',         desc: 'Tokeny, hashowanie haseł i progi wykrywania PII.' },
  pagination: { title: 'Paginacja i okna czasowe', desc: 'Domyślne i maksymalne rozmiary list oraz zakresy dni/godzin.' },
  compliance: { title: 'Compliance',             desc: 'Terminy luk zgodności i limity narracji raportów.' },
};

// ── Pojedynczy parametr ───────────────────────────────────────────────────────
function SettingRow({ setting, canEdit, onSaved }: {
  setting: Setting; canEdit: boolean; onSaved: (s: Setting) => void;
}) {
  const isJson = setting.value_type === 'json';
  const initial = isJson ? JSON.stringify(setting.value, null, 2) : setting.value;

  const [draft, setDraft] = useState<string | number | boolean>(initial as never);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const dirty = isJson
    ? draft !== JSON.stringify(setting.value, null, 2)
    : draft !== setting.value;

  async function save(nextValue?: boolean) {
    setSaving(true); setErr(null);
    try {
      let payload: unknown;
      if (isJson) {
        try { payload = JSON.parse(draft as string); }
        catch { setErr('Nieprawidłowy JSON'); setSaving(false); return; }
      } else if (setting.value_type === 'bool') {
        payload = nextValue ?? draft;
      } else if (setting.value_type === 'int' || setting.value_type === 'number') {
        payload = Number(draft);
      } else {
        payload = draft;
      }
      const updated = await api.settings.update(setting.key, payload);
      onSaved(updated);
      if (isJson) setDraft(JSON.stringify(updated.value, null, 2));
      else setDraft(updated.value as never);
    } catch (e) {
      setErr(String(e));
    } finally {
      setSaving(false);
    }
  }

  const range = (setting.min_value != null || setting.max_value != null)
    ? `${setting.min_value ?? '−∞'} … ${setting.max_value ?? '∞'}`
    : null;

  return (
    <div className="px-5 py-3 border-b border-blue/10 flex items-start gap-4">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-white">{setting.label}</span>
          <code className="text-[10px] text-mgray/40 font-mono">{setting.key}</code>
        </div>
        {setting.description && (
          <p className="text-xs text-mgray mt-0.5 leading-relaxed">{setting.description}</p>
        )}
        <div className="flex gap-3 mt-1 text-[10px] text-mgray/40">
          {setting.unit && <span>jednostka: {setting.unit}</span>}
          {range && <span>zakres: {range}</span>}
          {setting.updated_by && <span>ost. zmiana: {setting.updated_by}</span>}
        </div>
        {err && <p className="text-xs text-red-400 mt-1">{err}</p>}
      </div>

      {/* Edytor */}
      <div className="flex items-center gap-2 flex-shrink-0">
        {setting.value_type === 'bool' ? (
          <button
            disabled={!canEdit || saving}
            onClick={() => { const nv = !(draft as boolean); setDraft(nv); save(nv); }}
            className={`relative w-10 h-5 rounded-full transition-colors disabled:opacity-40 ${
              draft ? 'bg-teal' : 'bg-mgray/30'
            }`}
          >
            <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform ${
              draft ? 'translate-x-5' : 'translate-x-0.5'
            }`} />
          </button>
        ) : isJson ? (
          <textarea
            rows={6}
            disabled={!canEdit}
            value={draft as string}
            onChange={e => setDraft(e.target.value)}
            className="w-72 bg-dark border border-blue/30 rounded-lg px-3 py-2 text-xs text-white font-mono focus:outline-none focus:border-teal disabled:opacity-50 resize-y"
          />
        ) : (
          <input
            type={setting.value_type === 'string' ? 'text' : 'number'}
            disabled={!canEdit}
            value={draft as string | number}
            min={setting.min_value ?? undefined}
            max={setting.max_value ?? undefined}
            step="any"
            onChange={e => setDraft(setting.value_type === 'string' ? e.target.value : e.target.value)}
            className="w-44 bg-dark border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal disabled:opacity-50"
          />
        )}

        {setting.value_type !== 'bool' && canEdit && dirty && (
          <button
            onClick={() => save()}
            disabled={saving}
            className="px-3 py-1.5 bg-teal text-dark text-xs font-semibold rounded-lg hover:bg-teal/90 disabled:opacity-40"
          >
            {saving ? '...' : '✓ Zapisz'}
          </button>
        )}
      </div>
    </div>
  );
}

// ── Strona ────────────────────────────────────────────────────────────────────
export default function SettingsPage() {
  const { user } = useAuth();
  const canEdit = user?.role === 'it_admin';

  const [grouped, setGrouped] = useState<Record<string, Setting[]>>({});
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try { setGrouped(await api.settings.list()); }
    catch (e) { console.error(e); }
    finally { setLoading(false); }
  }

  useEffect(() => { load(); }, []);

  function onSaved(updated: Setting) {
    setGrouped(prev => {
      const next = { ...prev };
      const arr = next[updated.category];
      if (arr) next[updated.category] = arr.map(s => s.key === updated.key ? updated : s);
      return next;
    });
  }

  const categories = CATEGORY_ORDER.filter(c => grouped[c]?.length);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Parametry systemu</h1>
        <p className="text-mgray text-sm mt-1">
          Konfiguracja operacyjna bez zmian w kodzie. Zmiany aktywne natychmiast
          (gateway/API odświeżają wartości w ciągu 60s).
        </p>
      </div>

      {!canEdit && (
        <div className="bg-navy border border-orange-700/40 rounded-lg px-5 py-3 text-sm text-orange-300/90">
          Tryb podglądu — edycja parametrów wymaga roli <strong>it_admin</strong>.
          Twoja rola: <strong>{user?.role ?? '—'}</strong>.
        </div>
      )}

      {loading ? (
        <div className="text-mgray animate-pulse py-8">Ładowanie...</div>
      ) : (
        categories.map(cat => (
          <div key={cat} className="bg-navy border border-blue/30 rounded-xl overflow-hidden">
            <div className="px-5 py-3 border-b border-blue/20">
              <h2 className="text-white font-semibold text-sm">{CATEGORY_META[cat]?.title ?? cat}</h2>
              {CATEGORY_META[cat]?.desc && (
                <p className="text-xs text-mgray mt-0.5">{CATEGORY_META[cat].desc}</p>
              )}
            </div>
            <div>
              {grouped[cat].map(s => (
                <SettingRow key={s.key} setting={s} canEdit={canEdit} onSaved={onSaved} />
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
