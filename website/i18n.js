/*
 * GovAI — strona marketingowa: lekki silnik i18n po stronie przeglądarki (bez zależności, bez builda).
 *
 * Polski tekst zostaje w HTML jako domyślny (SEO + działanie bez JS). Pozostałe języki są ładowane
 * na żądanie z i18n/<lang>/<namespace>.json; strona deklaruje potrzebne namespace'y w
 * <body data-i18n-ns="common,index">. Klucz = "<namespace>.<ścieżka>", np. "common.nav.pricing".
 *
 * Atrybuty:
 *   data-i18n="ns.key"              — textContent
 *   data-i18n-html="ns.key"         — innerHTML (TYLKO nasze zaufane teksty z <strong>, <a>, <br>)
 *   data-i18n-placeholder="ns.key"  — atrybut placeholder
 *   data-i18n-attr="aria-label:ns.key;title:ns.key2" — dowolne atrybuty (aria-label, title, alt, content)
 *   data-app-link                   — link do aplikacji; dopisujemy ?lang=<aktywny język>
 *
 * Brak klucza lub pliku => zostaje polski tekst z HTML (zapamiętany przy starcie).
 * API dla skryptów stron: window.GovAII18N = { apply, t, lang, load, langs }.
 * Po każdej zmianie języka: document dispatchuje zdarzenie "govai:langchange" (detail.lang).
 */
(function () {
  'use strict';

  var STORAGE_KEY = 'govai_lang';
  var SOURCE = 'pl';

  var LANGS = [
    { code: 'pl', name: 'Polski' },
    { code: 'en', name: 'English' },
    { code: 'de', name: 'Deutsch' },
    { code: 'it', name: 'Italiano' },
    { code: 'es', name: 'Español' },
    { code: 'fr', name: 'Français' },
    { code: 'ro', name: 'Română' },
    { code: 'ru', name: 'Русский' },
    { code: 'sl', name: 'Slovenščina' },
    { code: 'hr', name: 'Hrvatski' },
    // Tylko landing page — aplikacja nie obsługuje portugalskiego (link "Zaloguj się"
    // dopisuje ?lang=pt, aplikacja go ignoruje i wybiera język z przeglądarki).
    { code: 'pt', name: 'Português' }
  ];

  var OG_LOCALES = {
    pl: 'pl_PL', en: 'en_GB', de: 'de_DE', it: 'it_IT', es: 'es_ES',
    fr: 'fr_FR', ro: 'ro_RO', ru: 'ru_RU', sl: 'sl_SI', hr: 'hr_HR', pt: 'pt_PT'
  };

  // Katalog słowników względem pliku i18n.js (nie względem adresu strony).
  var BASE = (function () {
    var s = document.currentScript;
    return (s && s.src ? s.src.replace(/[^\/]*$/, '') : '') + 'i18n/';
  })();

  var cache = {};      // "lang/ns" -> Promise<object|null>
  var tables = {};     // ns -> słownik aktywnego języka (puste dla pl)
  var current = SOURCE;
  var bindings = [];   // { el, kind: text|html|attr, name, key, value (polski oryginał) }
  var appLinks = [];   // { el, href }
  var pickers = [];    // { root, btn, menu, label }
  var requestId = 0;

  function isSupported(code) {
    for (var i = 0; i < LANGS.length; i++) if (LANGS[i].code === code) return true;
    return false;
  }

  function getByPath(obj, path) {
    var parts = path.split('.');
    var cur = obj;
    for (var i = 0; i < parts.length; i++) {
      if (cur == null || typeof cur !== 'object') return null;
      cur = cur[parts[i]];
    }
    return cur == null ? null : cur;
  }

  // Wartość z aktywnego języka (string) albo null, gdy brak — wtedy wołający bierze polski tekst.
  function lookup(key) {
    if (current === SOURCE) return null;
    var dot = key.indexOf('.');
    if (dot < 0) return null;
    var table = tables[key.slice(0, dot)];
    if (!table) return null;
    var val = getByPath(table, key.slice(dot + 1));
    return typeof val === 'string' && val !== '' ? val : null;
  }

  function format(str, params) {
    if (!params) return str;
    return str.replace(/\{(\w+)\}/g, function (m, name) {
      return Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : m;
    });
  }

  // t('index.contact.sending', 'Wysyłanie…') — drugi argument to polski tekst (fallback).
  function t(key, fallback, params) {
    var val = lookup(key);
    if (val == null) val = fallback != null ? fallback : key;
    return format(val, params);
  }

  function load(ns, lang) {
    lang = lang || current;
    var id = lang + '/' + ns;
    if (!cache[id]) {
      cache[id] = fetch(BASE + lang + '/' + ns + '.json')
        .then(function (r) { return r.ok ? r.json() : null; })
        .catch(function () { return null; });
    }
    return cache[id];
  }

  function namespaces() {
    var raw = (document.body && document.body.getAttribute('data-i18n-ns')) || 'common';
    return raw.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
  }

  function each(selector, fn) {
    var nodes = document.querySelectorAll(selector);
    for (var i = 0; i < nodes.length; i++) fn(nodes[i]);
  }

  // Zapamiętuje polskie oryginały z HTML — z nich przywracamy pl i bierzemy fallback.
  function capture() {
    each('[data-i18n]', function (el) {
      bindings.push({ el: el, kind: 'text', key: el.getAttribute('data-i18n'), value: el.textContent });
    });
    each('[data-i18n-html]', function (el) {
      bindings.push({ el: el, kind: 'html', key: el.getAttribute('data-i18n-html'), value: el.innerHTML });
    });
    each('[data-i18n-placeholder]', function (el) {
      bindings.push({ el: el, kind: 'attr', name: 'placeholder', key: el.getAttribute('data-i18n-placeholder'), value: el.getAttribute('placeholder') });
    });
    each('[data-i18n-attr]', function (el) {
      el.getAttribute('data-i18n-attr').split(';').forEach(function (pair) {
        var idx = pair.indexOf(':');
        if (idx < 1) return;
        var name = pair.slice(0, idx).trim();
        bindings.push({ el: el, kind: 'attr', name: name, key: pair.slice(idx + 1).trim(), value: el.getAttribute(name) });
      });
    });
    each('[data-app-link]', function (el) {
      appLinks.push({ el: el, href: el.getAttribute('href') || '' });
    });
  }

  function render() {
    for (var i = 0; i < bindings.length; i++) {
      var b = bindings[i];
      var val = lookup(b.key);
      if (val == null) val = b.value;
      if (b.kind === 'text') {
        if (b.el.textContent !== val) b.el.textContent = val;
      } else if (b.kind === 'html') {
        if (b.el.innerHTML !== val) b.el.innerHTML = val;
      } else if (val == null) {
        b.el.removeAttribute(b.name);
      } else {
        b.el.setAttribute(b.name, val);
      }
    }
    var og = document.querySelector('meta[property="og:locale"]');
    if (og) og.setAttribute('content', OG_LOCALES[current] || OG_LOCALES[SOURCE]);
  }

  function updateAppLinks() {
    appLinks.forEach(function (l) {
      var hashIdx = l.href.indexOf('#');
      var base = hashIdx >= 0 ? l.href.slice(0, hashIdx) : l.href;
      var hash = hashIdx >= 0 ? l.href.slice(hashIdx) : '';
      base = base.replace(/([?&])lang=[^&]*(&|$)/, function (m, pre, post) { return post ? pre : ''; });
      l.el.setAttribute('href', base + (base.indexOf('?') >= 0 ? '&' : '?') + 'lang=' + current + hash);
    });
  }

  function updatePickers() {
    pickers.forEach(function (p) {
      if (p.label) p.label.textContent = current.toUpperCase();
      var items = p.menu.querySelectorAll('button[data-code]');
      for (var i = 0; i < items.length; i++) {
        items[i].setAttribute('aria-current', items[i].getAttribute('data-code') === current ? 'true' : 'false');
      }
    });
  }

  function applyLang(code, persist) {
    if (!isSupported(code)) code = SOURCE;
    if (persist) {
      try { localStorage.setItem(STORAGE_KEY, code); } catch (e) {}
    }
    var id = ++requestId;
    var nss = namespaces();
    var pending = code === SOURCE
      ? Promise.resolve([])
      : Promise.all(nss.map(function (ns) { return load(ns, code); }));
    return pending.then(function (list) {
      if (id !== requestId) return current; // w międzyczasie wybrano inny język
      tables = {};
      nss.forEach(function (ns, i) { if (list[i]) tables[ns] = list[i]; });
      current = code;
      document.documentElement.setAttribute('lang', code);
      render();
      updateAppLinks();
      updatePickers();
      var ev;
      try {
        ev = new CustomEvent('govai:langchange', { detail: { lang: code } });
      } catch (e) {
        ev = document.createEvent('CustomEvent');
        ev.initCustomEvent('govai:langchange', false, false, { lang: code });
      }
      document.dispatchEvent(ev);
      return code;
    });
  }

  function detectLang() {
    try {
      var saved = localStorage.getItem(STORAGE_KEY);
      if (saved && isSupported(saved)) return saved;
    } catch (e) {}
    var nav = (navigator.language || SOURCE).slice(0, 2).toLowerCase();
    return isSupported(nav) ? nav : SOURCE;
  }

  // ---- Przełącznik języka: <div class="langpicker"><button class="langbtn">…</button><div class="langmenu"></div></div>
  function closePicker(p, focusBtn) {
    p.menu.hidden = true;
    p.btn.setAttribute('aria-expanded', 'false');
    if (focusBtn) p.btn.focus();
  }

  function openPicker(p) {
    pickers.forEach(function (o) { if (o !== p) closePicker(o, false); });
    p.menu.hidden = false;
    p.btn.setAttribute('aria-expanded', 'true');
    var active = p.menu.querySelector('button[aria-current="true"]') || p.menu.querySelector('button');
    if (active) active.focus();
  }

  function buildPicker(root, index) {
    var btn = root.querySelector('.langbtn');
    var menu = root.querySelector('.langmenu');
    if (!btn || !menu) return;
    var p = { root: root, btn: btn, menu: menu, label: root.querySelector('.langbtn-label') };
    var menuId = menu.id || ('langMenu' + index);
    menu.id = menuId;
    menu.setAttribute('role', 'menu');
    menu.hidden = true;
    btn.setAttribute('aria-haspopup', 'true');
    btn.setAttribute('aria-expanded', 'false');
    btn.setAttribute('aria-controls', menuId);

    LANGS.forEach(function (l) {
      var item = document.createElement('button');
      item.type = 'button';
      item.setAttribute('role', 'menuitem');
      item.setAttribute('data-code', l.code);
      item.setAttribute('lang', l.code);
      var name = document.createElement('span');
      name.textContent = l.name;
      var code = document.createElement('span');
      code.className = 'lang-code';
      code.textContent = l.code.toUpperCase();
      item.appendChild(name);
      item.appendChild(code);
      item.addEventListener('click', function () {
        closePicker(p, true);
        applyLang(l.code, true);
      });
      menu.appendChild(item);
    });

    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      if (menu.hidden) openPicker(p); else closePicker(p, false);
    });
    menu.addEventListener('keydown', function (e) {
      var items = Array.prototype.slice.call(menu.querySelectorAll('button'));
      var idx = items.indexOf(document.activeElement);
      if (e.key === 'ArrowDown') { e.preventDefault(); items[(idx + 1) % items.length].focus(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); items[(idx - 1 + items.length) % items.length].focus(); }
      else if (e.key === 'Home') { e.preventDefault(); items[0].focus(); }
      else if (e.key === 'End') { e.preventDefault(); items[items.length - 1].focus(); }
      else if (e.key === 'Tab') { closePicker(p, false); }
    });
    pickers.push(p);
  }

  function init() {
    capture();
    each('.langpicker', buildPicker);
    document.addEventListener('click', function (e) {
      pickers.forEach(function (p) {
        if (!p.menu.hidden && !p.root.contains(e.target)) closePicker(p, false);
      });
    });
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      pickers.forEach(function (p) { if (!p.menu.hidden) closePicker(p, true); });
    });
    var lang = detectLang();
    if (lang === SOURCE) {
      updateAppLinks();
      updatePickers();
    } else {
      applyLang(lang, false);
    }
  }

  window.GovAII18N = {
    apply: applyLang,
    t: t,
    lang: function () { return current; },
    load: load,
    langs: LANGS
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
