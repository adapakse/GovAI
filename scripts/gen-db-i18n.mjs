#!/usr/bin/env node
// Generator migracji z tłumaczeniami treści katalogowych w bazie.
//
//   node scripts/gen-db-i18n.mjs              — wartości już w bazie wygrywają (domyślnie)
//   node scripts/gen-db-i18n.mjs --overwrite  — tłumaczenia z plików wygrywają z bazą
//
// Źródło: db/i18n/<locale>/<tabela>.json. Polski (pl) to treść kolumn bazowych
// i wyznacza listę wierszy; pozostałe języki trafiają do kolumn *_i18n jako
// {"en": "...", "de": "...", ...}. Wynik: db/migrations/013_i18n_content.sql
// (idempotentny — deploy uruchamia wszystkie migracje przy każdym deployu).
//
// UPDATE scala JSON z bazą operatorem ||. Domyślnie wartości już zapisane w
// bazie wygrywają — tłumaczenie poprawione przez admina w UI nie zostanie
// nadpisane przy kolejnym deployu (jak ON CONFLICT DO NOTHING w seedach);
// pliki uzupełniają tylko brakujące języki. Poprawkę tłumaczenia z plików na
// istniejących instancjach wymusza migracja wygenerowana z --overwrite.
//
// Klucze wierszy:
//   ai_act_requirements — "<risk_level>|<article_ref>" (para unikalna w seedach
//                         001/006/011; decl_key bywa NULL, np. Art. 5),
//   app_settings        — app_settings.key,
//   providers           — providers.name (providerzy z seeda 003).
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const SRC = join(ROOT, 'db', 'i18n');
const OUT = join(ROOT, 'db', 'migrations', '013_i18n_content.sql');
const LOCALES = ['pl', 'en', 'de', 'it', 'es', 'fr', 'ro', 'ru', 'sl', 'hr'];
const SOURCE = 'pl';
const KEEP_EXISTING = !process.argv.includes('--overwrite');

// Tabele: plik źródłowy, pola tekstowe → kolumna JSONB, budowa warunku WHERE.
const TABLES = [
  {
    table: 'ai_act_requirements',
    fields: { title: 'title_i18n', text: 'text_i18n' },
    where: (key) => {
      const sep = key.indexOf('|');
      if (sep < 0) throw new Error(`ai_act_requirements: klucz bez "|": ${key}`);
      return `risk_level = ${lit(key.slice(0, sep))}::risk_level AND article_ref = ${lit(key.slice(sep + 1))}`;
    },
  },
  {
    table: 'app_settings',
    fields: { label: 'label_i18n', description: 'description_i18n', unit: 'unit_i18n' },
    where: (key) => `key = ${lit(key)}`,
  },
  {
    // Tylko providerzy z seeda (003) — po nazwie; własne wpisy użytkownika nie mają źródła w plikach.
    table: 'providers',
    fields: { notes: 'notes_i18n' },
    where: (key) => `name = ${lit(key)}`,
  },
];

// Literał SQL: apostrofy podwojone (standard_conforming_strings = on — backslash dosłowny).
function lit(value) {
  return `'${String(value).replace(/'/g, "''")}'`;
}

function readJson(file) {
  return existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : null;
}

const otherLocales = LOCALES.filter(
  (l) => l !== SOURCE && existsSync(join(SRC, l)) && readdirSync(join(SRC, l)).some((f) => f.endsWith('.json')),
);

const lines = [
  '-- GovAI — Tłumaczenia treści katalogowych (ai_act_requirements, app_settings, providers)',
  '--',
  '-- PLIK GENEROWANY — NIE EDYTUJ RĘCZNIE. Źródło: db/i18n/<locale>/*.json,',
  '-- generator: node scripts/gen-db-i18n.mjs' + (KEEP_EXISTING ? '' : ' --overwrite'),
  '--',
  '-- Kolumna bazowa (polski) nie jest zmieniana; uzupełniane są kolumny *_i18n.',
  KEEP_EXISTING
    ? '-- Tłumaczenia już zapisane w bazie (np. poprawione w UI) wygrywają; pliki uzupełniają brakujące języki.'
    : '-- Tryb --overwrite: tłumaczenia z plików nadpisują te same języki w bazie; pozostałe zostają.',
  '-- Idempotentna — deploy-remote.sh uruchamia wszystkie migracje przy każdym deployu.',
  '',
];

let statements = 0;
for (const { table, fields, where } of TABLES) {
  const base = readJson(join(SRC, SOURCE, `${table}.json`));
  if (!base) continue;
  const translations = Object.fromEntries(otherLocales.map((l) => [l, readJson(join(SRC, l, `${table}.json`)) || {}]));

  const block = [];
  for (const key of Object.keys(base).sort()) {
    const sets = [];
    for (const [field, column] of Object.entries(fields)) {
      // Pole bez treści polskiej (np. unit = NULL) nie ma czego tłumaczyć.
      if (typeof base[key]?.[field] !== 'string' || !base[key][field]) continue;
      const values = {};
      for (const loc of otherLocales) {
        const text = translations[loc]?.[key]?.[field];
        if (typeof text === 'string' && text.trim()) values[loc] = text;
      }
      // Brak tłumaczeń — nie dotykamy kolumny (żadnego nadpisania pustym obiektem).
      if (!Object.keys(values).length) continue;
      const json = `${lit(JSON.stringify(values))}::jsonb`;
      const current = `COALESCE(${column}, '{}'::jsonb)`;
      sets.push(`${column} = ${KEEP_EXISTING ? `${json} || ${current}` : `${current} || ${json}`}`);
    }
    if (!sets.length) continue;
    block.push(`UPDATE ${table} SET ${sets.join(',\n    ')}\n  WHERE ${where(key)};`);
    statements++;
  }

  lines.push(`-- ── ${table} ${'─'.repeat(Math.max(0, 70 - table.length))}`);
  lines.push(...(block.length ? block : ['-- (brak tłumaczeń)']));
  lines.push('');
}

writeFileSync(OUT, lines.join('\n'));
console.log(
  `✓ ${OUT.slice(ROOT.length + 1)}: ${statements} UPDATE, języki: ${otherLocales.length ? otherLocales.join(', ') : '(brak — tylko pl)'}`,
);
