'use client';

import { useEffect, useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import { api, Setting, SettingHistoryEntry } from '@/lib/api';
import { useAuth } from '@/components/AuthProvider';
import { useFormat } from '@/lib/format';
import { LOCALES, LOCALE_NAMES } from '@/i18n/locales';

// Tytuły i opisy kategorii: settings.categories.<cat>.title/desc
const CATEGORY_ORDER = [
  'pricing', 'budget', 'oversight', 'intervals',
  'models', 'security', 'pagination', 'compliance', 'i18n',
];

// Parametr języka domyślnego — edytowany listą wyboru, po zapisie przeładowanie strony.
const DEFAULT_LOCALE_KEY = 'i18n.default_locale';

function useFmtDate() {
  const fmt = useFormat();
  return (iso: string | null | undefined): string => {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    return fmt.dateTime(d, { dateStyle: 'medium', timeStyle: 'short' });
  };
}

function fmtVal(v: unknown): string {
  if (v === null || v === undefined) return '—';
  return typeof v === 'string' ? v : JSON.stringify(v);
}

// ── Historia zmian parametru ──────────────────────────────────────────────────
function SettingHistory({ settingKey }: { settingKey: string }) {
  const t = useTranslations('settings');
  const fmtDate = useFmtDate();
  const [entries, setEntries] = useState<SettingHistoryEntry[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.settings.history(settingKey)
      .then(rows => { if (!cancelled) setEntries(rows); })
      .catch(e => { if (!cancelled) setErr(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [settingKey]);

  if (loading) return <p className="text-xs text-mgray/60 italic">{t('history.loading')}</p>;
  if (err) return <p className="text-xs text-red-400">{err}</p>;
  if (!entries || entries.length === 0) return <p className="text-xs text-mgray/60 italic">{t('history.empty')}</p>;

  return (
    <ul className="space-y-1.5">
      {entries.map(e => (
        <li key={e.id} className="text-xs text-mgray flex flex-wrap gap-x-2">
          <span className="text-mgray/50">{fmtDate(e.updated_at)}</span>
          <span>{e.updated_by ?? t('history.unknownUser')}:</span>
          <code className="text-mgray/70">{fmtVal(e.old_value)}</code>
          <span className="text-mgray/40">→</span>
          <code className="text-white/80">{fmtVal(e.new_value)}</code>
        </li>
      ))}
    </ul>
  );
}

// ── Pojedynczy parametr ───────────────────────────────────────────────────────
function SettingRow({ setting, canEdit, onSaved }: {
  setting: Setting; canEdit: boolean; onSaved: (s: Setting) => void;
}) {
  const t = useTranslations('settings');
  const fmtDate = useFmtDate();
  const isJson = setting.value_type === 'json';
  const isLocale = setting.key === DEFAULT_LOCALE_KEY;
  const initial = isJson ? JSON.stringify(setting.value, null, 2) : setting.value;
  const editable = canEdit && setting.editable;

  const [draft, setDraft] = useState<string | number | boolean>(initial as never);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  const dirty = isJson
    ? draft !== JSON.stringify(setting.value, null, 2)
    : draft !== setting.value;

  async function save(nextValue?: boolean) {
    setSaving(true); setErr(null);
    try {
      let payload: unknown;
      if (isJson) {
        try { payload = JSON.parse(draft as string); }
        catch { setErr(t('row.invalidJson')); setSaving(false); return; }
      } else if (setting.value_type === 'bool') {
        payload = nextValue ?? draft;
      } else if (setting.value_type === 'int' || setting.value_type === 'number') {
        payload = Number(draft);
      } else {
        payload = draft;
      }
      const updated = await api.settings.update(setting.key, payload);
      // Zmiana języka domyślnego instancji — przeładuj, żeby UI wczytało nowy język.
      if (isLocale) { window.location.reload(); return; }
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
          {!setting.editable && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-orange-900/40 text-orange-300/90">
              {t('row.locked')}
            </span>
          )}
        </div>
        {setting.description && (
          <p className="text-xs text-mgray mt-0.5 leading-relaxed">{setting.description}</p>
        )}
        <div className="flex gap-3 mt-1 text-[10px] text-mgray/40 flex-wrap items-center">
          {setting.unit && <span>{t('row.unit', { unit: setting.unit })}</span>}
          {range && <span>{t('row.range', { range })}</span>}
          {setting.updated_by && (
            <span>{t('row.lastChange', { user: setting.updated_by, date: fmtDate(setting.updated_at) })}</span>
          )}
          <button
            onClick={() => setShowHistory(v => !v)}
            className="text-mgray/50 hover:text-teal underline underline-offset-2"
          >
            {showHistory ? t('row.hideHistory') : t('row.showHistory')}
          </button>
        </div>
        {showHistory && (
          <div className="mt-2 pl-2 border-l border-blue/20">
            <SettingHistory settingKey={setting.key} />
          </div>
        )}
        {err && <p className="text-xs text-red-400 mt-1">{err}</p>}
      </div>

      {/* Edytor */}
      <div className="flex items-center gap-2 flex-shrink-0">
        {setting.value_type === 'bool' ? (
          <button
            disabled={!editable || saving}
            onClick={() => { const nv = !(draft as boolean); setDraft(nv); save(nv); }}
            className={`relative w-10 h-5 rounded-full transition-colors disabled:opacity-40 ${
              draft ? 'bg-teal' : 'bg-mgray/30'
            }`}
          >
            <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform ${
              draft ? 'translate-x-5' : 'translate-x-0.5'
            }`} />
          </button>
        ) : isLocale ? (
          <select
            disabled={!editable}
            value={String(draft ?? '')}
            onChange={e => setDraft(e.target.value)}
            className="w-44 bg-dark border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal disabled:opacity-50"
          >
            {LOCALES.map(code => (
              <option key={code} value={code}>{LOCALE_NAMES[code]}</option>
            ))}
          </select>
        ) : isJson ? (
          <textarea
            rows={6}
            disabled={!editable}
            value={draft as string}
            onChange={e => setDraft(e.target.value)}
            className="w-72 bg-dark border border-blue/30 rounded-lg px-3 py-2 text-xs text-white font-mono focus:outline-none focus:border-teal disabled:opacity-50 resize-y"
          />
        ) : (
          <input
            type={setting.value_type === 'string' ? 'text' : 'number'}
            disabled={!editable}
            value={draft as string | number}
            min={setting.min_value ?? undefined}
            max={setting.max_value ?? undefined}
            step="any"
            onChange={e => setDraft(setting.value_type === 'string' ? e.target.value : e.target.value)}
            className="w-44 bg-dark border border-blue/30 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal disabled:opacity-50"
          />
        )}

        {setting.value_type !== 'bool' && editable && dirty && (
          <button
            onClick={() => save()}
            disabled={saving}
            className="px-3 py-1.5 bg-teal text-dark text-xs font-semibold rounded-lg hover:bg-teal/90 disabled:opacity-40"
          >
            {saving ? '...' : t('row.save')}
          </button>
        )}
      </div>
    </div>
  );
}

// ── Strona ────────────────────────────────────────────────────────────────────
export default function SettingsPage() {
  const t = useTranslations('settings');
  const { user } = useAuth();
  const canEdit = user?.role === 'it_admin';

  const [grouped, setGrouped] = useState<Record<string, Setting[]>>({});
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [reloading, setReloading] = useState(false);
  const [reloadMsg, setReloadMsg] = useState<string | null>(null);

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

  async function onReload() {
    setReloading(true); setReloadMsg(null);
    try {
      await api.settings.reload();
      setReloadMsg(t('reload.done'));
    } catch (e) {
      setReloadMsg(t('reload.error', { error: String(e) }));
    } finally {
      setReloading(false);
      setTimeout(() => setReloadMsg(null), 4000);
    }
  }

  const q = query.trim().toLowerCase();
  const filtered = useMemo(() => {
    if (!q) return grouped;
    const out: Record<string, Setting[]> = {};
    for (const [cat, items] of Object.entries(grouped)) {
      const matches = items.filter(s =>
        s.label.toLowerCase().includes(q) ||
        s.key.toLowerCase().includes(q) ||
        (s.description ?? '').toLowerCase().includes(q)
      );
      if (matches.length) out[cat] = matches;
    }
    return out;
  }, [grouped, q]);

  const categories = CATEGORY_ORDER.filter(c => filtered[c]?.length);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-white">{t('title')}</h1>
          <p className="text-mgray text-sm mt-1">
            {t('subtitle')}
          </p>
        </div>
        {canEdit && (
          <div className="flex items-center gap-2">
            {reloadMsg && <span className="text-xs text-mgray">{reloadMsg}</span>}
            <button
              onClick={onReload}
              disabled={reloading}
              className="px-3 py-1.5 bg-navy border border-blue/30 text-white text-xs font-semibold rounded-lg hover:border-teal disabled:opacity-40"
            >
              {reloading ? t('reload.running') : t('reload.button')}
            </button>
          </div>
        )}
      </div>

      {!canEdit && (
        <div className="bg-navy border border-orange-700/40 rounded-lg px-5 py-3 text-sm text-orange-300/90">
          {t.rich('readOnly', {
            b: (c) => <strong>{c}</strong>,
            role: user?.role ?? '—',
          })}
        </div>
      )}

      <input
        type="text"
        value={query}
        onChange={e => setQuery(e.target.value)}
        placeholder={t('searchPlaceholder')}
        className="w-full max-w-md bg-navy border border-blue/30 rounded-lg px-3 py-2 text-sm text-white placeholder:text-mgray/50 focus:outline-none focus:border-teal"
      />

      {loading ? (
        <div className="text-mgray animate-pulse py-8">{t('loading')}</div>
      ) : categories.length === 0 ? (
        <div className="text-mgray text-sm py-8">{t('noResults', { query })}</div>
      ) : (
        categories.map(cat => (
          <div key={cat} className="bg-navy border border-blue/30 rounded-xl overflow-hidden">
            <div className="px-5 py-3 border-b border-blue/20">
              <h2 className="text-white font-semibold text-sm">
                {t.has(`categories.${cat}.title`) ? t(`categories.${cat}.title`) : cat}
              </h2>
              {t.has(`categories.${cat}.desc`) && (
                <p className="text-xs text-mgray mt-0.5">{t(`categories.${cat}.desc`)}</p>
              )}
            </div>
            <div>
              {filtered[cat].map(s => (
                <SettingRow key={s.key} setting={s} canEdit={canEdit} onSaved={onSaved} />
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
