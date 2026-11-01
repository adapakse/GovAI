#!/usr/bin/env node
// Kontrola kompletności tłumaczeń GovAI (wzorowana na CRMtree scripts/i18n-check.mjs).
//
//   node scripts/i18n-check.mjs         — sprawdza, kod wyjścia 1 przy błędach
//   node scripts/i18n-check.mjs --fix   — przepisuje pliki do formatu kanonicznego
//
// Dla każdego katalogu tłumaczeń (<root>/<locale>/<namespace>.json) sprawdza:
//   1. każdy język ma plik dla każdego namespace z języka źródłowego (pl),
//   2. każdy język ma dokładnie klucze z pl — bez braków, nadmiarów i pustych tekstów,
//   3. teksty mają te same {parametry} na najwyższym poziomie co tekst polski,
//   4. (frontend) każdy tekst kompiluje się jako komunikat ICU dla swojego języka,
//   5. pliki są w formacie kanonicznym (klucze posortowane rekurencyjnie, wcięcie 2).
import { readFileSync, readdirSync, writeFileSync, existsSync, statSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const LOCALES = ['pl', 'en', 'de', 'it', 'es', 'fr', 'ro', 'ru', 'sl', 'hr'];
const SOURCE = 'pl';
const FIX = process.argv.includes('--fix');

const CATALOGS = [
  { root: 'frontend/messages', icu: true },
  { root: 'api/i18n/locales', icu: false },
  { root: 'gateway/i18n/locales', icu: false },
  // Landing page ma dodatkowo portugalski (aplikacja — nie).
  { root: 'website/i18n', icu: false, extraLocales: ['pt'] },
  { root: 'db/i18n', icu: false },
];

// intl-messageformat przychodzi z next-intl (frontend/node_modules) — bez niego
// pomijamy tylko kontrolę składni ICU, reszta działa.
let IntlMessageFormat = null;
try {
  const require = createRequire(join(ROOT, 'frontend', 'package.json'));
  IntlMessageFormat = require('intl-messageformat').IntlMessageFormat;
} catch {
  console.warn('! intl-messageformat niedostępne (npm ci w frontend/) — pomijam kontrolę składni ICU');
}

const errors = [];
const err = (file, msg) => errors.push(`${relative(ROOT, file)}: ${msg}`);

function sortDeep(value) {
  if (Array.isArray(value)) return value.map(sortDeep);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map(k => [k, sortDeep(value[k])]));
  }
  return value;
}

function flatten(obj, prefix = '', out = {}) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === 'object' && !Array.isArray(v)) flatten(v, key, out);
    else out[key] = v;
  }
  return out;
}

// Nazwy parametrów na najwyższym poziomie: {name} albo {count, plural, ...}.
// Treść wewnątrz gałęzi ICU (np. "# elementów") jest pomijana. Apostrof przed
// klamrą escapuje ją tylko w ICU — w str.format (api/gateway/db) to zwykły znak.
function placeholders(text, icu = true) {
  if (typeof text !== 'string') return [];
  const names = new Set();
  let depth = 0;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (icu && c === "'" && (text[i + 1] === '{' || text[i + 1] === '}')) { i++; continue; }
    if (c === '{') {
      if (depth === 0) {
        const m = /^\{\s*([A-Za-z_][\w]*)\s*[,}]/.exec(text.slice(i));
        if (m) names.add(m[1]);
      }
      depth++;
    } else if (c === '}') {
      depth = Math.max(0, depth - 1);
    }
  }
  return [...names].sort();
}

function readJson(file) {
  const raw = readFileSync(file, 'utf8');
  try {
    return { raw, data: JSON.parse(raw) };
  } catch (e) {
    err(file, `niepoprawny JSON: ${e.message}`);
    return { raw, data: null };
  }
}

function checkCatalog({ root, icu, extraLocales = [] }) {
  const base = join(ROOT, root);
  const sourceDir = join(base, SOURCE);
  if (!existsSync(sourceDir)) return;
  const namespaces = readdirSync(sourceDir).filter(f => f.endsWith('.json')).sort();

  for (const locale of [...LOCALES, ...extraLocales]) {
    const dir = join(base, locale);
    const present = existsSync(dir) && statSync(dir).isDirectory()
      ? readdirSync(dir).filter(f => f.endsWith('.json'))
      : [];
    for (const extra of present.filter(f => !namespaces.includes(f))) {
      err(join(dir, extra), `namespace nieobecny w ${SOURCE}`);
    }
    for (const ns of namespaces) {
      const file = join(dir, ns);
      if (!existsSync(file)) { err(file, 'brak pliku'); continue; }
      const { raw, data } = readJson(file);
      if (!data) continue;

      const canonical = JSON.stringify(sortDeep(data), null, 2) + '\n';
      if (raw.replace(/\r\n/g, '\n') !== canonical) {
        if (FIX) writeFileSync(file, canonical);
        else err(file, 'format niekanoniczny (uruchom z --fix)');
      }

      if (locale === SOURCE) {
        if (icu) for (const [k, v] of Object.entries(flatten(data))) compileIcu(file, k, v, locale);
        continue;
      }
      const src = flatten(readJson(join(sourceDir, ns)).data ?? {});
      const tgt = flatten(data);
      for (const k of Object.keys(src)) {
        if (!(k in tgt)) { err(file, `brak klucza ${k}`); continue; }
        // Tablice (np. akapity artykułów bloga) — ta sama długość, każdy element sprawdzany osobno.
        if (Array.isArray(src[k])) {
          if (!Array.isArray(tgt[k]) || tgt[k].length !== src[k].length) {
            err(file, `${k}: tablica ma ${Array.isArray(tgt[k]) ? tgt[k].length : 0} elementów zamiast ${src[k].length}`);
            continue;
          }
          src[k].forEach((s, i) => checkText(file, `${k}[${i}]`, s, tgt[k][i], icu, locale));
          continue;
        }
        checkText(file, k, src[k], tgt[k], icu, locale);
      }
      for (const k of Object.keys(tgt)) if (!(k in src)) err(file, `nadmiarowy klucz ${k}`);
    }
  }
}

function checkText(file, key, source, text, icu, locale) {
  if (typeof text !== 'string' || text.trim() === '') { err(file, `pusty tekst ${key}`); return; }
  const want = placeholders(source, icu).join(',');
  const got = placeholders(text, icu).join(',');
  if (want !== got) err(file, `${key}: parametry {${got}} zamiast {${want}}`);
  if (icu) compileIcu(file, key, text, locale);
}

function compileIcu(file, key, text, locale) {
  if (!IntlMessageFormat || typeof text !== 'string') return;
  try {
    new IntlMessageFormat(text, locale);
  } catch (e) {
    err(file, `${key}: niepoprawny komunikat ICU (${e.message})`);
  }
}

for (const catalog of CATALOGS) checkCatalog(catalog);

if (errors.length) {
  console.error(`i18n-check: ${errors.length} błędów\n` + errors.map(e => `  - ${e}`).join('\n'));
  process.exit(1);
}
console.log(`i18n-check: OK${FIX ? ' (pliki sformatowane)' : ''}`);
