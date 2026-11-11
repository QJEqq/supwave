"""Веб-морда аугментера: одна страница без данных и без токена внутри.

Токен (ADMIN_TOKEN) вводится на ней, живёт только в браузере (sessionStorage или,
с «запомнить», localStorage) и уходит в /admin/* заголовком Authorization. Всё
выводится через textContent (никакого innerHTML с данными), внешних скриптов,
шрифтов и картинок нет — CSP страницы (app.py) их и не пустит.
"""

import os
import re
import urllib.parse

# Название в шапке, на входе и во вкладке. Меняется BRAND_NAME в .env (буквы, цифры,
# пробел, точка, дефис — чтобы не ломать HTML и JS страницы).
BRAND = os.getenv("BRAND_NAME", "").strip()
if not re.fullmatch(r"[\w .-]{1,40}", BRAND):
    BRAND = "Supwave"

# Логотип — снежный барс (свой рисунок, 128×128). Градиент меха — два цвета stop-color.
_LOGO = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" aria-hidden="true" focusable="false">
<defs>
<linearGradient id="fur" gradientUnits="userSpaceOnUse" x1="0" y1="16" x2="0" y2="112">
<stop offset="0" stop-color="#1b57c9"/>
<stop offset="1" stop-color="#46c4ef"/>
</linearGradient>
</defs>
<path fill="url(#fur)" d="M19 54 Q14 26 26 19 Q34 15 54 33 Z"/>
<path fill="url(#fur)" d="M109 54 Q114 26 102 19 Q94 15 74 33 Z"/>
<path fill="#0e3a82" fill-opacity=".3" d="M24 46 Q22 30 29 26 Q34 24 44 34 Z"/>
<path fill="#0e3a82" fill-opacity=".3" d="M104 46 Q106 30 99 26 Q94 24 84 34 Z"/>
<path fill="url(#fur)" d="M64 28 C86 28 101 36 105 52 C108 63 111 71 115.5 79.5 C112 82 110.5 85 109 89 C101 104 83 110 64 110 C45 110 27 104 19 89 C17.5 85 16 82 12.5 79.5 C17 71 20 63 23 52 C27 36 42 28 64 28 Z"/>
<g fill="#0e3a82" fill-opacity=".32">
<circle cx="64" cy="38" r="3"/><circle cx="56" cy="43.5" r="2.4"/><circle cx="72" cy="43.5" r="2.4"/>
<circle cx="64" cy="48" r="1.9"/><circle cx="49" cy="37" r="1.8"/><circle cx="79" cy="37" r="1.8"/>
</g>
<g fill="none" stroke="#0e3a82" stroke-opacity=".32" stroke-width="2.3" stroke-linecap="round">
<circle cx="26" cy="74" r="4.4" stroke-dasharray="20 8"/>
<circle cx="102" cy="74" r="4.4" stroke-dasharray="20 8" transform="rotate(180 102 74)"/>
<circle cx="32" cy="90" r="3" stroke-dasharray="13 6"/>
<circle cx="96" cy="90" r="3" stroke-dasharray="13 6" transform="rotate(180 96 90)"/>
</g>
<ellipse cx="45" cy="63" rx="12.5" ry="10.5" fill="#fff" transform="rotate(16 45 63)"/>
<ellipse cx="83" cy="63" rx="12.5" ry="10.5" fill="#fff" transform="rotate(-16 83 63)"/>
<ellipse cx="46" cy="63.5" rx="4.8" ry="7.6" fill="#0b2e6b"/>
<ellipse cx="82" cy="63.5" rx="4.8" ry="7.6" fill="#0b2e6b"/>
<circle cx="44.6" cy="60" r="1.7" fill="#fff"/><circle cx="80.6" cy="60" r="1.7" fill="#fff"/>
<circle cx="57" cy="90" r="8.6" fill="#eaf8ff"/>
<circle cx="71" cy="90" r="8.6" fill="#eaf8ff"/>
<path fill="#0b2e6b" d="M58 82 C60.5 80.4 67.5 80.4 70 82 C69 85.4 66.4 87.8 64 88.2 C61.6 87.8 59 85.4 58 82 Z"/>
<path fill="none" stroke="#0b2e6b" stroke-width="1.6" stroke-linecap="round" d="M64 88.2 V91 M64 91 Q61.2 94 58.4 92.2 M64 91 Q66.8 94 69.6 92.2"/>
<g fill="#0b2e6b" fill-opacity=".45">
<circle cx="52.5" cy="89" r="1"/><circle cx="55" cy="93.2" r="1"/><circle cx="51.2" cy="93.6" r="1"/>
<circle cx="75.5" cy="89" r="1"/><circle cx="73" cy="93.2" r="1"/><circle cx="76.8" cy="93.6" r="1"/>
</g>
</svg>"""


def logo(uid: str) -> str:
    """Свой id градиента у каждой копии: Chrome не рисует градиент, объявленный в
    скрытой (display:none) копии, а экран входа после входа как раз скрыт."""
    return _LOGO.replace('"fur"', f'"sw-{uid}"').replace("#fur)", f"#sw-{uid})")

_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<link rel="icon" href="data:image/svg+xml,{{FAVICON}}">
<title>{{BRAND}}</title>
<style>
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --hair: #e1e0d9; --border: rgba(11,11,11,0.10); --accent: #2a78d6; --on-accent: #ffffff;
  --good: #0ca30c; --warning: #fab219; --serious: #ec835a; --critical: #d03b3b;
  --wash: rgba(11,11,11,0.04);
  /* цвета столбцов (у каждого свой; зелёный, жёлтый, красный — только у статусов) */
  --c1: #2a78d6; --c2: #6250d6; --c3: #0f9fc4; --c4: #d55181; --c5: #eb6834; --c6: #607089; --c7: #9a6b3f; --c8: #4b5bdc;
  /* статусы online / processing / offline */
  --on: #12b886; --proc: #e9a400; --off: #e5484d;
  --brand-a: #2a6fdc; --brand-b: #3fb8ea;
  --glass: rgba(252,252,251,0.82);
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
    --hair: #2c2c2a; --border: rgba(255,255,255,0.10); --accent: #3987e5; --wash: rgba(255,255,255,0.05);
    --c1: #3987e5; --c2: #9085e9; --c3: #3ab7dd; --c4: #e87ba4; --c5: #f08a5d; --c6: #94a3b8; --c7: #c4935f; --c8: #8b96f2;
    --on: #2fd39b; --proc: #f5c044; --off: #ff6b6b; --brand-a: #4b8ff0; --brand-b: #5fd3f3;
    --glass: rgba(26,26,25,0.78);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
  --hair: #2c2c2a; --border: rgba(255,255,255,0.10); --accent: #3987e5; --wash: rgba(255,255,255,0.05);
  --c1: #3987e5; --c2: #9085e9; --c3: #3ab7dd; --c4: #e87ba4; --c5: #f08a5d; --c6: #94a3b8; --c7: #c4935f; --c8: #8b96f2;
  --on: #2fd39b; --proc: #f5c044; --off: #ff6b6b; --brand-a: #4b8ff0; --brand-b: #5fd3f3;
  --glass: rgba(26,26,25,0.78);
}
* { box-sizing: border-box; }
html, body { margin: 0; }
body { color: var(--ink); font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; min-height: 100vh;
  /* «северное сияние» в цветах барса + россыпь снежинок-точек */
  background-color: var(--page);
  background-image:
    radial-gradient(1100px 560px at 6% -16%, color-mix(in srgb, var(--brand-a) 22%, transparent), transparent 66%),
    radial-gradient(900px 520px at 104% -10%, color-mix(in srgb, var(--brand-b) 20%, transparent), transparent 62%),
    radial-gradient(1000px 640px at 50% 122%, color-mix(in srgb, var(--c2) 10%, transparent), transparent 62%),
    radial-gradient(color-mix(in srgb, var(--ink) 9%, transparent) 1px, transparent 1.3px);
  background-size: auto, auto, auto, 26px 26px;
  background-attachment: fixed; }
[hidden] { display: none !important; }
.wrap { max-width: 1400px; margin: 0 auto; padding: 20px 16px 48px; }
h1 { font-size: 20px; font-weight: 700; letter-spacing: -.01em; margin: 0; }
.b1 { background: linear-gradient(180deg, var(--brand-a), var(--brand-b)); -webkit-background-clip: text; background-clip: text; color: transparent; }
h2 { font-size: 16px; font-weight: 600; margin: 0; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12.5px; }
.muted { color: var(--muted); }
.ink2 { color: var(--ink-2); }
.num { font-variant-numeric: tabular-nums; }
a { color: var(--accent); }

/* шапка */
.top { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; justify-content: space-between; }
.top .meta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.chip { display: inline-flex; align-items: center; padding: 2px 10px; border-radius: 999px; font-size: 12px; line-height: 18px; color: var(--ink-2);
  background: color-mix(in srgb, var(--muted) 10%, transparent); border: 1px solid color-mix(in srgb, var(--muted) 38%, transparent); overflow-wrap: anywhere; }
.brand { display: flex; align-items: flex-start; gap: 12px; min-width: 0; }
.brand > svg { flex: none; width: 40px; height: 40px; }
.brand.big { flex-direction: column; align-items: flex-start; gap: 10px; margin-bottom: 4px; }
.brand.big > svg { width: 60px; height: 60px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin: 16px 0 8px; }
.tile { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; min-width: 0; }
.tile .label { color: var(--ink-2); font-size: 12.5px; }
.tile .value { font-size: 22px; font-weight: 600; margin: 2px 0 4px; }
.tile .sub { color: var(--ink-2); font-size: 12.5px; display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: center; }
.tile .btn { margin-top: 8px; }
.meter { height: 8px; border-radius: 4px; background: color-mix(in srgb, var(--accent) 16%, transparent); overflow: hidden; margin: 6px 0 4px; }
.meter > span { display: block; height: 100%; border-radius: 4px; background: var(--accent); }
.meter.warn > span { background: var(--warning); }
.meter.crit > span { background: var(--critical); }

/* вкладки */
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--hair); margin: 18px 0 14px; overflow-x: auto; }
.tabs button { appearance: none; border: 0; background: none; color: var(--ink-2); font: inherit; padding: 8px 12px; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; white-space: nowrap; }
.tabs button[aria-selected="true"] { color: var(--ink); border-bottom-color: var(--accent); font-weight: 600; }
.tabs button:hover { color: var(--ink); }
.bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.bar .grow { flex: 1; }
.hint { color: var(--ink-2); font-size: 12.5px; margin: 8px 0 12px; max-width: 80ch; }
.empty { color: var(--ink-2); background: var(--surface); border: 1px dashed var(--hair); border-radius: 12px; padding: 20px; text-align: center; }

/* таблицы */
.tablewrap { overflow-x: auto; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--hair); vertical-align: middle; white-space: nowrap; }
th { color: var(--ink-2); font-weight: 500; font-size: 12.5px; }
tbody tr:last-child td { border-bottom: 0; }
tbody tr:hover { background: var(--wash); }
td.actions { text-align: right; }
.acts { display: inline-flex; gap: 6px; justify-content: flex-end; }
td .small { display: block; color: var(--muted); font-size: 12px; }

/* статус: цвет только у значка, подпись — обычным текстом */
.st { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
/* овальчики: у каждого столбца свой цвет (--h), текст — подкрашенный тон того же цвета */
.pill { --h: var(--c6); display: inline-flex; align-items: center; gap: 6px; padding: 2px 10px; border-radius: 999px; font-size: 12px; line-height: 18px;
  white-space: nowrap; background: color-mix(in srgb, var(--h) 13%, transparent); border: 1px solid color-mix(in srgb, var(--h) 34%, transparent);
  color: color-mix(in srgb, var(--h) 50%, var(--ink)); }
.pill.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11.5px; }
.pill.c1 { --h: var(--c1); } .pill.c2 { --h: var(--c2); } .pill.c3 { --h: var(--c3); } .pill.c4 { --h: var(--c4); }
.pill.c5 { --h: var(--c5); } .pill.c6 { --h: var(--c6); } .pill.c7 { --h: var(--c7); } .pill.c8 { --h: var(--c8); }
.pill.muted { --h: var(--muted); color: var(--ink-2); }
/* online / processing / offline */
.pill.s3 { font-weight: 600; letter-spacing: .01em; }
.pill.s3::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--h); }
.pill.on { --h: var(--on); background: color-mix(in srgb, var(--on) 17%, transparent); border-color: color-mix(in srgb, var(--on) 45%, transparent); }
.pill.proc { --h: var(--proc); background: color-mix(in srgb, var(--proc) 17%, transparent); border-color: color-mix(in srgb, var(--proc) 50%, transparent); }
.pill.off { --h: var(--off); background: color-mix(in srgb, var(--off) 15%, transparent); border-color: color-mix(in srgb, var(--off) 45%, transparent); }
.pill.proc::before { animation: blink 1.4s ease-in-out infinite; }
@keyframes blink { 50% { opacity: .3; } }
@media (prefers-reduced-motion: reduce) { .pill.proc::before { animation: none; } }
.cellrow { display: inline-flex; align-items: center; gap: 8px; }
.cellrow .small { display: inline; }
.st-i { font-size: 11px; line-height: 1; }
.st-good .st-i { color: var(--good); }
.st-warning .st-i { color: var(--warning); }
.st-serious .st-i { color: var(--serious); }
.st-critical .st-i { color: var(--critical); }
.st-muted { color: var(--ink-2); }
.st-muted .st-i { color: var(--muted); }

/* кнопки и поля */
.btn { appearance: none; font: inherit; font-size: 13px; border: 1px solid var(--border); background: var(--surface); color: var(--ink); border-radius: 8px; padding: 6px 12px; cursor: pointer; }
.btn:hover { background: var(--wash); }
.btn.primary { background: var(--accent); color: var(--on-accent); border-color: transparent; }
.btn.primary:hover { filter: brightness(1.06); }
.btn.danger { color: var(--critical); }
.btn:disabled { opacity: .45; cursor: not-allowed; }
.btn.small { padding: 3px 8px; font-size: 12px; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
label.f { display: block; margin: 0 0 12px; }
label.f > span { display: block; color: var(--ink-2); font-size: 12.5px; margin-bottom: 4px; }
input[type=text], input[type=password], input[type=number], input[type=search], textarea {
  width: 100%; font: inherit; color: var(--ink); background: var(--page); border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; }
textarea { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; min-height: 160px; resize: vertical; }
input[type=search] { width: auto; min-width: 200px; padding: 6px 10px; }
.check { display: flex; gap: 8px; align-items: center; color: var(--ink-2); margin: 0 0 14px; }

/* вход */
.login { min-height: 100vh; display: grid; place-items: center; padding: 16px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 22px; width: min(400px, 100%); }
.card h1 { margin-bottom: 4px; }
.card p { color: var(--ink-2); margin: 0 0 16px; font-size: 13px; }
.err { color: var(--ink); background: color-mix(in srgb, var(--critical) 12%, transparent); border-radius: 8px; padding: 8px 10px; margin: 0 0 12px; font-size: 13px; }

/* журнал */
.log { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 10px 12px; margin: 0;
  max-height: 64vh; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; line-height: 1.55; }
.log .t { color: var(--muted); user-select: none; }

/* настройки */
.set { background: var(--glass); -webkit-backdrop-filter: blur(12px); backdrop-filter: blur(12px); border: 1px solid var(--border);
  border-radius: 12px; padding: 14px 16px; margin: 0 0 14px; max-width: 880px; }
.set h3 { font-size: 15px; font-weight: 600; margin: 0 0 4px; }
.set .check { margin: 6px 0; color: var(--ink); }
.set .bar { margin: 10px 0 0; }
.set input[type=text] { max-width: 440px; }
.sqlist { display: grid; gap: 2px; margin: 2px 0 8px 26px; }
.sqlist.dim { opacity: .4; pointer-events: none; }
.sq { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 4px 0; cursor: pointer; }
/* полупрозрачные карточки поверх фона */
.tile, .tablewrap, .card, .log, .empty { background: var(--glass); -webkit-backdrop-filter: blur(12px); backdrop-filter: blur(12px); }
/* окна */
dialog { border: 1px solid var(--border); border-radius: 14px; background: var(--surface); color: var(--ink); padding: 0; width: min(760px, calc(100vw - 32px)); max-height: calc(100vh - 32px); }
dialog::backdrop { background: rgba(0,0,0,.4); }
.dlg-h { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 14px 18px; border-bottom: 1px solid var(--hair); }
.dlg-b { padding: 16px 18px; overflow-y: auto; max-height: calc(100vh - 160px); }
.dlg-f { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 18px; border-top: 1px solid var(--hair); }
.steps { margin: 0; padding: 0; list-style: none; counter-reset: s; }
.steps > li { counter-increment: s; position: relative; padding-left: 30px; margin: 0 0 14px; }
.steps > li::before { content: counter(s); position: absolute; left: 0; top: 0; width: 20px; height: 20px; border-radius: 50%;
  background: var(--wash); border: 1px solid var(--border); font-size: 12px; display: grid; place-items: center; color: var(--ink-2); }
.cmd { display: flex; gap: 8px; align-items: flex-start; margin-top: 6px; }
.cmd code { flex: 1; min-width: 0; background: var(--page); border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; overflow-wrap: anywhere; }
.note { background: var(--wash); border-radius: 8px; padding: 8px 10px; font-size: 12.5px; color: var(--ink-2); margin: 10px 0 0; }

/* всплывашка */
#toast { position: fixed; left: 50%; bottom: 20px; transform: translateX(-50%); background: var(--ink); color: var(--page);
  padding: 9px 14px; border-radius: 10px; font-size: 13px; max-width: calc(100vw - 32px); box-shadow: 0 4px 16px rgba(0,0,0,.2); z-index: 10; }
#toast .st-i { margin-right: 6px; }

@media (max-width: 640px) {
  .tiles { grid-template-columns: 1fr 1fr; gap: 8px; }
  .tile { padding: 10px 12px; }
  .tile .value { font-size: 20px; }
  input[type=search] { min-width: 0; flex: 1; }
}
</style>
</head>
<body>

<div id="login" class="login" hidden>
  <form id="login-form" class="card" autocomplete="off">
    <div class="brand big">{{LOGO_LOGIN}}<h1>{{BRAND_HTML}}</h1></div>
    <p>Вход по ADMIN_TOKEN — он в .env на панели.</p>
    <div id="login-err" class="err" role="alert" hidden></div>
    <label class="f"><span>Токен</span><input id="login-token" type="password" required spellcheck="false"></label>
    <label class="check"><input id="login-remember" type="checkbox"> Запомнить на этом устройстве</label>
    <button class="btn primary" type="submit">Войти</button>
  </form>
</div>

<div id="app" class="wrap" hidden>
  <div class="top">
    <div class="brand">{{LOGO_TOP}}<div><h1>{{BRAND_HTML}}</h1><div id="meta" class="meta"></div></div></div>
    <button id="logout" class="btn" type="button">Выйти</button>
  </div>
  <div id="tiles" class="tiles" aria-live="polite"></div>
  <div class="tabs" role="tablist">
    <button role="tab" data-tab="nodes">Ноды</button>
    <button role="tab" data-tab="channels">Каналы</button>
    <button role="tab" data-tab="pool">Пул аккаунтов</button>
    <button role="tab" data-tab="log">Журнал</button>
    <button role="tab" data-tab="settings">Настройки</button>
  </div>
  <section id="tab-nodes" role="tabpanel"></section>
  <section id="tab-channels" role="tabpanel" hidden></section>
  <section id="tab-pool" role="tabpanel" hidden></section>
  <section id="tab-log" role="tabpanel" hidden></section>
  <section id="tab-settings" role="tabpanel" hidden></section>
</div>

<dialog id="dlg"></dialog>
<div id="toast" role="status" aria-live="polite" hidden></div>

<script>
'use strict';
const KEY = 'augmenter.token';
// API — под тем же префиксом, что и страница (/admin/ или ADMIN_PREFIX на домене панели).
const BASE = location.pathname.replace(/\/+$/, '');
const S = { token: '', summary: null, nodes: null, channels: null, accounts: null, log: [], logFilter: '', tab: 'nodes', busy: new Set() };
const NAMES = { boards: 'доска', vyandex: 'волга', direct: 'direct' };
const $ = (sel) => document.querySelector(sel);

function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2), v);
    else if (k === 'value') e.value = v;
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    e.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return e;
}

// ---- API -------------------------------------------------------------------
class AuthError extends Error {}
async function call(method, path, body, raw) {
  const headers = { Authorization: 'Bearer ' + S.token };
  if (typeof body === 'string') headers['Content-Type'] = 'text/plain; charset=utf-8';
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(body); }
  let r;
  try { r = await fetch(path, { method, headers, body, cache: 'no-store' }); }
  catch (e) { throw new Error('{{BRAND}} не отвечает'); }
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
  // Без верного токена /admin/* отвечает пустым 404 — как будто их нет.
  if (r.status === 404 && !text) throw new AuthError('токен не подходит');
  if (!r.ok) throw new Error((data && (data.detail || data.error)) || ('ошибка ' + r.status));
  return raw ? text : data;
}

// ---- мелочи ----------------------------------------------------------------
function status(kind, label, title) {
  const icon = { good: '●', warning: '◆', serious: '▲', critical: '✕', muted: '○' }[kind] || '○';
  return el('span', { class: 'st st-' + kind, title: title || null }, el('span', { class: 'st-i', 'aria-hidden': 'true' }, icon), label);
}
function pill(text, cls, title) {
  return el('span', { class: 'pill ' + (cls || ''), title: title || null }, text);
}
const S3 = { online: 'on', processing: 'proc', offline: 'off' };
// online / processing / offline; label — своя подпись (вход: «ок», «нужен вход»)
function s3(status, title, label) {
  return el('span', { class: 'pill s3 ' + (S3[status] || 'off'), title: title || null }, label || status || 'offline');
}
function bytes(n) {
  if (!n) return '0 Б';
  const u = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ'];
  let i = 0, v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return (i === 0 || v >= 100 ? Math.round(v) : v.toFixed(1)) + ' ' + u[i];
}
function ago(ts) {
  if (!ts) return 'никогда';
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 45) return 'только что';
  if (s < 3600) return Math.round(s / 60) + ' мин назад';
  if (s < 86400) return Math.round(s / 3600) + ' ч назад';
  return new Date(ts * 1000).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}
function hhmmss(ts) { return new Date(ts * 1000).toLocaleTimeString('ru-RU', { hour12: false }); }
let toastTimer = 0;
function toast(msg, kind) {
  const t = $('#toast');
  t.replaceChildren(kind ? el('span', { class: 'st-' + kind }, el('span', { class: 'st-i', 'aria-hidden': 'true' }, kind === 'critical' ? '✕' : '●')) : '', msg);
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, kind === 'critical' ? 7000 : 3500);
}
function fail(e) {
  if (e instanceof AuthError) { logout('Токен больше не подходит — войди заново.'); return; }
  toast(e.message || String(e), 'critical');
}
async function copy(text, btn) {
  try { await navigator.clipboard.writeText(text); }
  catch (e) {
    const ta = el('textarea', { style: 'position:fixed;opacity:0' }); ta.value = text; document.body.append(ta);
    ta.select(); document.execCommand('copy'); ta.remove();
  }
  if (btn) { const was = btn.textContent; btn.textContent = 'Скопировано'; setTimeout(() => { btn.textContent = was; }, 1500); }
}

// ---- окна --------------------------------------------------------------------
function openDialog(title, body, footer) {
  const d = $('#dlg');
  const close = el('button', { class: 'btn small', type: 'button', 'aria-label': 'Закрыть', onclick: () => d.close() }, '✕');
  d.replaceChildren(el('div', { class: 'dlg-h' }, el('h2', {}, title), close), el('div', { class: 'dlg-b' }, body),
    footer ? el('div', { class: 'dlg-f' }, footer) : '');
  if (!d.open) d.showModal();
  return d;
}
function confirmBox(title, text, ok, danger) {
  return new Promise((resolve) => {
    const d = $('#dlg');
    let answered = false;
    const done = (v) => { answered = true; d.close(); resolve(v); };
    openDialog(title, el('p', { class: 'ink2', style: 'margin:0' }, text), [
      el('button', { class: 'btn', type: 'button', onclick: () => done(false) }, 'Отмена'),
      el('button', { class: 'btn ' + (danger ? 'danger' : 'primary'), type: 'button', onclick: () => done(true) }, ok),
    ]);
    d.addEventListener('close', () => { if (!answered) resolve(false); }, { once: true });
  });
}
function cmdRow(text) {
  const b = el('button', { class: 'btn small', type: 'button' }, 'Копировать');
  b.addEventListener('click', () => copy(text, b));
  return el('div', { class: 'cmd' }, el('code', { class: 'mono' }, text), b);
}

// ---- загрузка ----------------------------------------------------------------
// Перерисовка — только когда данные поменялись (и раз в минуту, чтобы «N мин назад»
// не застывало): иначе кнопка исчезала бы прямо под курсором и клик терялся.
const drawn = {};
function changed(name, data) {
  const key = JSON.stringify(data) + '|' + Math.floor(Date.now() / 60000);
  if (drawn[name] === key) return false;
  drawn[name] = key;
  return true;
}
function drawTop() { if (changed('top', [S.summary, S.nodes && S.nodes.map((n) => n.status)])) renderTop(); }
async function loadSummary() { S.summary = await call('GET', BASE + '/summary'); drawTop(); }
async function loadNodes() { S.nodes = (await call('GET', BASE + '/nodes')).nodes; drawTop(); if (S.tab === 'nodes' && changed('nodes', S.nodes)) renderNodes(); }
async function loadChannels() { S.channels = (await call('GET', BASE + '/channels')).channels; if (S.tab === 'channels' && changed('channels', [S.channels, [...S.busy]])) renderChannels(); }
async function loadPool() { S.accounts = (await call('GET', BASE + '/accounts')).accounts; if (S.tab === 'pool' && changed('pool', S.accounts)) renderPool(); }
async function loadLog() { S.log = (await call('GET', BASE + '/log?n=500')).lines; if (S.tab === 'log') renderLog(); }
async function loadSettings() { S.settings = await call('GET', BASE + '/settings'); if (S.tab === 'settings') renderSettings(); }
const LOADERS = { nodes: loadNodes, channels: loadChannels, pool: loadPool, log: loadLog, settings: loadSettings };

async function refresh() {
  try {
    await loadSummary();
    const jobs = [loadNodes()];
    if (S.tab !== 'nodes' && S.tab !== 'settings') jobs.push(LOADERS[S.tab]());  // настройки не перерисовываем под руками
    await Promise.all(jobs);
  } catch (e) { fail(e); }
}

// ---- шапка -------------------------------------------------------------------
function tile(label, value, ...sub) {
  return el('div', { class: 'tile' }, el('div', { class: 'label' }, label), el('div', { class: 'value num' }, value), ...sub);
}
function reconcileSub(r) {
  const parts = [];
  if (r.mode === 'off') parts.push('выключена (RECONCILE_MODE=off)');
  else if (r.running) parts.push('идёт сейчас…');
  else if (r.finished) {
    parts.push(ago(r.finished));
    parts.push('+' + r.added + ' −' + r.removed + (r.failed ? ' · ошибок: ' + r.failed : ''));
  } else parts.push('ещё не было');
  if (r.mode !== 'off') parts.push('каждые ' + Math.round(r.interval / 60) + ' мин');
  return parts;
}
function renderTop() {
  const s = S.summary;
  if (!s) return;
  const prios = Object.entries(s.priorities || {}).filter(([k]) => k !== 'error').sort((a, b) => b[1] - a[1])
    .map(([k, v]) => (NAMES[k] || k) + ' ' + v).join(' → ');
  const chips = ['режим ' + s.node_mode, s.direct ? 'с direct' : 'без direct'];
  if (prios) chips.push(prios);
  const sq = s.squads || {};
  chips.push('openflux → ' + (sq.mode === 'all' ? 'всем активным' : (sq.names && sq.names.length ? sq.names.join(', ') : 'никому')));
  chips.push('ядро ' + (s.core || '—'), 'образ нод ' + s.node_image);
  if (s.provision_mode === 'stub') chips.push('провижн-заглушка');
  $('#meta').replaceChildren(...chips.map((c) => el('span', { class: 'chip' }, c)));
  const nodes = S.nodes || [];
  const byStatus = {};
  nodes.forEach((n) => { byStatus[n.status] = (byStatus[n.status] || 0) + 1; });
  const seats = s.pool.total * s.pool_max_docs;
  const used = s.pool.active_docs;
  const pct = seats ? Math.min(100, Math.round(used * 100 / seats)) : 0;
  const r = s.reconcile;
  const rbtn = el('button', { class: 'btn small', type: 'button', disabled: r.mode === 'off' || r.running }, r.running ? 'Сверка идёт…' : 'Сверить сейчас');
  rbtn.addEventListener('click', reconcileNow);
  $('#tiles').replaceChildren(
    tile('Ноды online', S.nodes ? (byStatus.online || 0) + ' из ' + nodes.length : '…',
      el('div', { class: 'sub' }, !S.nodes ? '' : !nodes.length ? 'нод нет'
        : ['online', 'processing', 'offline'].filter((k) => byStatus[k]).map((k) => s3(k, null, byStatus[k] + ' ' + k)))),
    tile('Каналы', String(s.channels), el('div', { class: 'sub' }, s.channels ? 'по одному на юзера' : 'заведутся на сверке')),
    tile('Пул аккаунтов', s.pool.healthy + ' из ' + s.pool.total,
      el('div', { class: 'meter' + (pct >= 90 ? ' crit' : pct >= 70 ? ' warn' : ''), role: 'meter', 'aria-label': 'Занято мест под каналы',
        'aria-valuemin': '0', 'aria-valuemax': String(seats), 'aria-valuenow': String(used) }, el('span', { style: 'width:' + pct + '%' })),
      el('div', { class: 'sub' }, 'каналов на аккаунтах: ' + used + ' из ' + seats)),
    tile('Сверка', r.mode === 'off' ? 'выключена' : r.mode === 'dryrun' ? 'проба' : 'включена',
      el('div', { class: 'sub' }, reconcileSub(r).map((p) => el('span', {}, p))),
      r.error ? el('div', { class: 'sub' }, status('critical', r.error)) : r.note ? el('div', { class: 'sub' }, status('warning', r.note)) : '',
      rbtn),
  );
}
async function reconcileNow() {
  try {
    const r = await call('POST', BASE + '/reconcile');
    toast(r.busy ? 'Сверка уже идёт' : 'Сверка запущена', 'good');
    for (let i = 0; i < 60; i++) {
      await new Promise((res) => setTimeout(res, 3000));
      await loadSummary();
      if (!S.summary.reconcile.running) break;
    }
    await refresh();
  } catch (e) { fail(e); }
}

// ---- ноды --------------------------------------------------------------------
function coreCell(n) {
  if (!n.connected) return pill('—', 'muted');
  return el('span', { class: 'cellrow' },
    pill(n.core || '?', 'c5 mono', n.core_current ? 'ядро актуальное' : 'обновится на сверке; ядро {{BRAND}}: ' + (S.summary ? S.summary.core : '?')),
    el('span', { class: 'small' }, (n.core_current ? 'актуальное' : 'обновится') + ' · ' + (n.core_from === 'pushed' ? 'залито {{BRAND}}' : 'из образа')));
}
function nodeTitle(n) {
  if (n.status === 'processing') return n.connected ? 'ядро обновится на ближайшей сверке' : 'ждём первого подключения: на ноде docker compose up -d';
  return n.connected ? 'агент отвечает' : (n.error || 'не отвечает');
}
function renderNodes() {
  const box = $('#tab-nodes');
  const add = el('button', { class: 'btn primary', type: 'button', onclick: addNodeForm }, '+ Добавить ноду');
  const head = el('div', { class: 'bar' }, el('h2', {}, 'Ноды'), el('span', { class: 'grow' }), add);
  if (!S.nodes) { box.replaceChildren(head, el('p', { class: 'muted' }, 'Загружаю…')); return; }
  const body = !S.nodes.length
    ? el('div', { class: 'empty' }, 'Нод пока нет. «Добавить ноду» выдаст готовый docker-compose.yml — на ноде останется docker compose up -d.')
    : el('div', { class: 'tablewrap' }, el('table', {},
        el('thead', {}, el('tr', {}, ['Нода', 'Адрес', 'Связь', 'Агент', 'Ядро', 'Каналов', ''].map((t) => el('th', { scope: 'col' }, t)))),
        el('tbody', {}, S.nodes.map((n) => {
          const comp = el('button', { class: 'btn small', type: 'button', onclick: () => showCompose(n) }, 'compose');
          const del = el('button', { class: 'btn small danger', type: 'button', disabled: n.channels > 0,
            title: n.channels > 0 ? 'На ноде есть каналы — удалить нельзя' : 'Убрать ноду из {{BRAND}}', onclick: () => deleteNode(n) }, 'удалить');
          const onNode = n.connected && n.channels_on_node !== n.channels
            ? pill('на ноде ' + n.channels_on_node, 'muted', 'каналов на самой ноде — не столько, сколько у {{BRAND}}') : '';
          return el('tr', {},
            el('td', {}, pill(n.name, 'c1')),
            el('td', {}, pill(n.address + ':' + n.port, 'c3 mono')),
            el('td', {}, s3(n.status, nodeTitle(n))),
            el('td', {}, n.agent ? pill(n.agent, 'c2 mono') : pill('—', 'muted')),
            el('td', {}, coreCell(n)),
            el('td', {}, el('span', { class: 'cellrow' }, pill(String(n.channels), 'c4'), onNode)),
            el('td', { class: 'actions' }, el('div', { class: 'acts' }, comp, del)));
        }))));
  box.replaceChildren(head, body,
    el('p', { class: 'hint' }, 'Ядро на ноды {{BRAND}} заливает сам на каждой сверке. Агента на ноде обновить: docker compose pull && docker compose up -d.'));
}
function addNodeForm() {
  const name = el('input', { type: 'text', required: true, placeholder: 'nl-2', maxlength: '40', spellcheck: 'false' });
  const addr = el('input', { type: 'text', required: true, placeholder: 'IP или имя хоста ноды', spellcheck: 'false' });
  const port = el('input', { type: 'number', required: true, min: '1', max: '65535', value: '2223' });
  const err = el('div', { class: 'err', role: 'alert', hidden: true });
  const form = el('form', { id: 'node-form' },
    err,
    el('label', { class: 'f' }, el('span', {}, 'Имя (для себя)'), name),
    el('label', { class: 'f' }, el('span', {}, 'Адрес ноды — по нему {{BRAND}} будет ходить к агенту'), addr),
    el('label', { class: 'f' }, el('span', {}, 'Порт API агента (открыть только для IP панели)'), port));
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    err.hidden = true;
    try {
      const q = new URLSearchParams({ name: name.value.trim(), address: addr.value.trim(), port: port.value });
      const r = await call('POST', BASE + '/nodes?' + q);
      composeDialog({ id: r.id, name: r.name, address: r.address, port: r.port }, r.compose);
      loadNodes().catch(fail);
    } catch (e) {
      if (e instanceof AuthError) return fail(e);
      err.textContent = e.message; err.hidden = false;
    }
  });
  openDialog('Добавить ноду', form, [
    el('button', { class: 'btn', type: 'button', onclick: () => $('#dlg').close() }, 'Отмена'),
    el('button', { class: 'btn primary', type: 'submit', form: 'node-form' }, 'Получить compose'),
  ]);
  setTimeout(() => name.focus(), 0);
}
async function showCompose(n) {
  try { composeDialog(n, await call('GET', BASE + '/nodes/' + n.id + '/compose', undefined, true)); }
  catch (e) { fail(e); }
}
function composeDialog(n, compose) {
  const s = S.summary || {};
  const panel = s.panel_ip || '<IP панели>';
  const ta = el('textarea', { readonly: true, rows: '14', spellcheck: 'false' }); ta.value = compose;
  const cbtn = el('button', { class: 'btn primary', type: 'button' }, 'Скопировать compose');
  cbtn.addEventListener('click', () => copy(compose, cbtn));
  const notes = [];
  if (!s.panel_ip) notes.push(el('p', { class: 'note' }, 'IP панели не задан: впиши его в команду сам или задай PANEL_IP в .env на панели — тогда подставится.'));
  if (s.node_image && !s.node_image.includes('/')) notes.push(el('p', { class: 'note' }, 'Образ нод «' + s.node_image + '» локальный — из реестра он не скачается. Задай OPENFLUX_NODE_IMAGE (Docker Hub) в .env на панели.'));
  openDialog('Нода «' + n.name + '»', [
    el('ol', { class: 'steps' },
      el('li', {}, 'На ноде поставь Docker, если его нет', cmdRow('curl -fsSL https://get.docker.com | sh')),
      el('li', {}, 'Открой API агента только для панели — других портов нода не открывает', cmdRow('ufw allow from ' + panel + ' to any port ' + n.port + ' proto tcp')),
      el('li', {}, 'Сохрани compose ниже как /opt/openflux-node/docker-compose.yml', cmdRow('mkdir -p /opt/openflux-node && nano /opt/openflux-node/docker-compose.yml')),
      el('li', {}, 'Запусти — нода подключится сама, ядро зальёт {{BRAND}}', cmdRow('cd /opt/openflux-node && docker compose up -d'))),
    el('div', { class: 'bar' }, el('b', {}, 'docker-compose.yml'), el('span', { class: 'grow' }), cbtn),
    ta,
    el('p', { class: 'note' }, 'В compose — SECRET_KEY этой ноды (её токен и сертификат). Не пересылай его в открытых чатах.'),
    notes,
  ], [el('button', { class: 'btn', type: 'button', onclick: () => $('#dlg').close() }, 'Готово')]);
}
async function deleteNode(n) {
  if (!(await confirmBox('Убрать ноду «' + n.name + '»?', '{{BRAND}} забудет ноду и её ключ. Контейнер на самой ноде останется — его гасить руками: docker compose down.', 'Убрать', true))) return;
  try { await call('DELETE', BASE + '/nodes/' + n.id); toast('Нода «' + n.name + '» убрана', 'good'); await refresh(); }
  catch (e) { fail(e); }
}

// ---- каналы ------------------------------------------------------------------
function stateCell(c) {
  if (c.busy || S.busy.has(c.short_uuid)) return s3('processing', 'пересоздаётся');
  const why = {
    running: c.restarts ? 'работает; перезапусков: ' + c.restarts : 'работает',
    restarting: 'перезапускается (' + c.restarts + ')' + (c.last_exit ? ': ' + c.last_exit : ''),
    stopped: 'остановлен', missing: 'канал есть в складе, но не на ноде — пересоздай',
    unknown: 'нода не ответила',
  }[c.state] || 'не на ноде-агенте';
  return s3(c.status, why);
}
const OLD_AGENT = 'агент ноды без статистики — обнови образ ноды: docker compose pull && docker compose up -d';
function carriersTitle(st) {
  return (st.carriers || []).map((x) => (NAMES[x.name] || x.name) + ': ' + (x.up ? 'поднят' : 'не поднят') +
    ', ↓ ' + bytes(x.total_sent) + ' ↑ ' + bytes(x.total_recv) + (x.reconnects ? ', переподключений ' + x.reconnects : '')).join('\n');
}
function carrierCell(c) {
  const st = c.stats;
  if (!st) return pill('—', 'muted', c.state === 'running' ? OLD_AGENT : null);
  if (st.active) return pill(NAMES[st.active] || st.active, 'c5', carriersTitle(st));
  const up = (st.carriers || []).filter((x) => x.up).map((x) => NAMES[x.name] || x.name);
  return pill(up.length ? up.join(' · ') : 'нет', 'muted', (up.length ? 'подняты, клиента нет\n' : 'ни один носитель не поднят\n') + carriersTitle(st));
}
function trafficCell(c) {
  const st = c.stats;
  if (!st) return pill('—', 'muted');
  return pill('↓ ' + bytes(st.total_sent) + '  ↑ ' + bytes(st.total_recv), 'c8',
    '↓ — ушло юзеру, ↑ — пришло от него; за всё время канала\n' + carriersTitle(st));
}
function clientCell(c) {
  const st = c.stats;
  if (!st) return pill('—', 'muted');
  if (!st.heard) return pill('не было', 'muted', 'клиент ещё не подключался');
  const now = Date.now() / 1000 - st.heard < 90;
  return pill(now ? 'сейчас' : ago(st.heard), now ? 'c7' : 'muted', st.client ? 'клиент подключён' : 'последний раз слышали ' + ago(st.heard));
}
function signinCell(c) {
  const bad = c.signin || [];
  if (!c.stats && !bad.length) return pill('—', 'muted');
  const login = bad.find((x) => x.state === 'login');
  if (login) return s3('offline', 'Яндекс просит вход с ' + ago(login.since) + ' — свежие куки в пул и пересоздать канал\n' + login.doc, 'нужен вход');
  const down = bad.find((x) => x.state === 'down');
  if (down) return s3('processing', 'не на связи с ' + ago(down.since) + '\n' + down.doc, 'нет связи');
  return s3('online', 'вход оператора в Яндекс жив', 'ок');
}
function coreUseCell(c) {
  if (!c.since) return pill('—', 'muted', c.stats ? null : (c.state === 'running' ? OLD_AGENT : null));
  if (!c.rss) return pill('запущено ' + ago(c.since), 'c6', 'CPU и память не видны (нет /proc)');
  return pill('CPU ' + (c.cpu || 0) + '% · ' + bytes(c.rss), 'c6', 'ядро канала запущено ' + ago(c.since));
}
async function showLog(c) {
  const pre = el('pre', { class: 'log mono', tabindex: '0', 'aria-label': 'Журнал канала' }, el('span', { class: 'muted' }, 'Загружаю…'));
  const load = async () => {
    try {
      const r = await call('GET', BASE + '/channels/' + encodeURIComponent(c.short_uuid) + '/log');
      pre.replaceChildren(...(r.lines.length ? r.lines.map((l) => el('div', {}, l)) : [el('span', { class: 'muted' }, 'Пока пусто.')]));
      pre.scrollTop = pre.scrollHeight;
    } catch (e) {
      if (e instanceof AuthError) return fail(e);
      pre.replaceChildren(el('span', { class: 'muted' }, e.message));
    }
  };
  openDialog('Журнал канала ' + c.channel, [
    el('p', { class: 'hint' }, 'Последние 200 строк ядра канала на ноде ' + (c.node || '?') + ' · юзер ' + c.short_uuid), pre],
    [el('button', { class: 'btn', type: 'button', onclick: load }, 'Обновить'),
     el('button', { class: 'btn', type: 'button', onclick: () => $('#dlg').close() }, 'Закрыть')]);
  load();
}
function renderChannels() {
  const box = $('#tab-channels');
  const head = el('div', { class: 'bar' }, el('h2', {}, 'Каналы'), el('span', { class: 'muted' }, S.channels ? S.channels.length + ' шт.' : ''));
  const hint = el('p', { class: 'hint' }, 'Канал заводится сам на сверке каждому юзеру из нужного сквада. Снять доступ — в Remnawave (отключить, дать истечь или убрать из сквада): {{BRAND}} снимет канал на ближайшей сверке.');
  if (!S.channels) { box.replaceChildren(head, hint, el('p', { class: 'muted' }, 'Загружаю…')); return; }
  const body = !S.channels.length
    ? el('div', { class: 'empty' }, 'Каналов пока нет.')
    : el('div', { class: 'tablewrap' }, el('table', {},
        el('thead', {}, el('tr', {}, ['Юзер (shortUuid)', 'Канал', 'Нода', 'Аккаунт', 'Состояние', 'Носитель', 'Трафик', 'Клиент', 'Вход', 'Ядро', ''].map((t) => el('th', { scope: 'col' }, t)))),
        el('tbody', {}, S.channels.map((c) => {
          const link = el('button', { class: 'btn small', type: 'button' }, 'ссылка');
          link.addEventListener('click', async () => {
            try { copy((await call('GET', BASE + '/channels/' + encodeURIComponent(c.short_uuid) + '/link')).link, link); }
            catch (e) { fail(e); }
          });
          const busy = c.busy || S.busy.has(c.short_uuid);
          const redo = el('button', { class: 'btn small', type: 'button', disabled: busy, onclick: () => reprovision(c) }, 'пересоздать');
          const log = el('button', { class: 'btn small', type: 'button', disabled: !c.node, onclick: () => showLog(c) }, 'журнал');
          return el('tr', {},
            el('td', {}, pill(c.short_uuid, 'c1 mono')),
            el('td', {}, pill(c.channel, 'c2 mono')),
            el('td', {}, c.node ? pill(c.node, 'c3') : pill('—', 'muted')),
            el('td', {}, c.account ? pill(c.account, 'c4') : pill('общий из env', 'muted')),
            el('td', {}, stateCell(c)),
            el('td', {}, carrierCell(c)),
            el('td', {}, trafficCell(c)),
            el('td', {}, clientCell(c)),
            el('td', {}, signinCell(c)),
            el('td', {}, coreUseCell(c)),
            el('td', { class: 'actions' }, el('div', { class: 'acts' }, log, link, redo)));
        }))));
  box.replaceChildren(head, hint, body);
}
async function reprovision(c) {
  const ok = await confirmBox('Пересоздать канал ' + c.short_uuid + '?',
    'Канал снимется с ноды и заведётся заново: новые доска и документ, новый ключ. У юзера сменится ссылка — подтянется со следующим обновлением подписки.', 'Пересоздать');
  if (!ok) return;
  try {
    await call('POST', BASE + '/channels/' + encodeURIComponent(c.short_uuid) + '/reprovision');
    S.busy.add(c.short_uuid); renderChannels();
    toast('Пересоздаю канал ' + c.short_uuid, 'good');
    for (let i = 0; i < 80; i++) {
      await new Promise((res) => setTimeout(res, 3000));
      await loadChannels();
      const row = (S.channels || []).find((x) => x.short_uuid === c.short_uuid);
      if (row && !row.busy) break;  // пока строки нет или она занята — канал ещё заводится
    }
  } catch (e) { fail(e); }
  finally { S.busy.delete(c.short_uuid); if (S.tab === 'channels') renderChannels(); loadSummary().catch(() => {}); }
}

// ---- пул ---------------------------------------------------------------------
function renderPool() {
  const box = $('#tab-pool');
  const max = S.summary ? S.summary.pool_max_docs : '?';
  const head = el('div', { class: 'bar' }, el('h2', {}, 'Пул аккаунтов Яндекса'), el('span', { class: 'grow' }),
    el('button', { class: 'btn primary', type: 'button', onclick: addAccountForm }, '+ Добавить аккаунт'));
  const hint = el('p', { class: 'hint' }, 'По кукам оператора для каждого канала создаются своя доска и свой документ. До ' + max + ' каналов на аккаунт; «прижат» — Яндекс начал отказывать (капча, бан), новых каналов на нём не заводится.');
  if (!S.accounts) { box.replaceChildren(head, hint, el('p', { class: 'muted' }, 'Загружаю…')); return; }
  const body = !S.accounts.length
    ? el('div', { class: 'empty' }, 'Пул пуст — каналы заводятся на общих доске и документе из env (если они заданы).')
    : el('div', { class: 'tablewrap' }, el('table', {},
        el('thead', {}, el('tr', {}, ['Аккаунт', 'Состояние', 'Каналов', 'Заведено всего', 'Последний раз', ''].map((t) => el('th', { scope: 'col' }, t)))),
        el('tbody', {}, S.accounts.map((a) => {
          const acts = [];
          if (!a.healthy) acts.push(el('button', { class: 'btn small', type: 'button', onclick: () => healAccount(a) }, 'вернуть в ротацию'));
          acts.push(el('button', { class: 'btn small danger', type: 'button', onclick: () => deleteAccount(a) }, 'удалить'));
          return el('tr', {},
            el('td', {}, el('span', { class: 'cellrow' }, pill(a.label || '#' + a.id, 'c4'), el('span', { class: 'small' }, '#' + a.id))),
            el('td', {}, a.healthy ? s3('online', 'новые каналы заводятся на нём', 'в ротации') : s3('offline', 'Яндекс начал отказывать (капча, бан): новых каналов на нём нет', 'прижат')),
            el('td', {}, pill(a.active_docs + ' из ' + max, 'c1')),
            el('td', {}, pill(String(a.created_docs), 'c2')),
            el('td', {}, pill(ago(a.last_used), 'c6')),
            el('td', { class: 'actions' }, el('div', { class: 'acts' }, acts)));
        }))));
  box.replaceChildren(head, hint, body);
}
function addAccountForm() {
  const label = el('input', { type: 'text', placeholder: 'по умолчанию — логин Яндекса из кук', spellcheck: 'false' });
  const ta = el('textarea', { required: true, spellcheck: 'false', placeholder: '# Netscape HTTP Cookie File\n.yandex.ru\tTRUE\t/\tTRUE\t…' });
  const file = el('input', { type: 'file', accept: '.txt,text/plain' });
  file.addEventListener('change', () => {
    const f = file.files && file.files[0];
    if (!f) return;
    const rd = new FileReader();
    rd.onload = () => { ta.value = String(rd.result || ''); };
    rd.readAsText(f);
  });
  const err = el('div', { class: 'err', role: 'alert', hidden: true });
  const form = el('form', { id: 'acc-form' }, err,
    el('label', { class: 'f' }, el('span', {}, 'Метка'), label),
    el('label', { class: 'f' }, el('span', {}, 'cookies.txt из браузера, где выполнен вход в Яндекс (можно полный экспорт — возьмутся только куки yandex.ru)'), ta),
    el('label', { class: 'f' }, el('span', {}, 'или файлом'), file),
    el('p', { class: 'note' }, 'Куки — это вход в аккаунт. Они уходят только в {{BRAND}} по HTTPS и хранятся в его базе.'));
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    err.hidden = true;
    try {
      const r = await call('POST', BASE + '/accounts?' + new URLSearchParams({ label: label.value.trim() }), ta.value);
      ta.value = '';
      $('#dlg').close();
      toast('Аккаунт «' + (r.label || '#' + r.id) + '» добавлен: кук ' + r.cookies + (r.sessionid2 ? '' : ', без sessionid2 — вход может не принять'), r.sessionid2 ? 'good' : 'critical');
      await Promise.all([loadPool(), loadSummary()]);
    } catch (e) {
      if (e instanceof AuthError) return fail(e);
      err.textContent = e.message; err.hidden = false;
    }
  });
  openDialog('Добавить аккаунт в пул', form, [
    el('button', { class: 'btn', type: 'button', onclick: () => $('#dlg').close() }, 'Отмена'),
    el('button', { class: 'btn primary', type: 'submit', form: 'acc-form' }, 'Добавить'),
  ]);
}
async function healAccount(a) {
  try { await call('POST', BASE + '/accounts/' + a.id + '/healthy'); toast('«' + (a.label || '#' + a.id) + '» снова в ротации', 'good'); await Promise.all([loadPool(), loadSummary()]); }
  catch (e) { fail(e); }
}
async function deleteAccount(a) {
  const extra = a.active_docs ? ' На нём ' + a.active_docs + ' канал(ов): они продолжат работать, но их доски и документы останутся на этом аккаунте.' : '';
  if (!(await confirmBox('Удалить аккаунт «' + (a.label || '#' + a.id) + '»?', 'Куки аккаунта удалятся из пула.' + extra, 'Удалить', true))) return;
  try { await call('DELETE', BASE + '/accounts/' + a.id); toast('Аккаунт удалён', 'good'); await Promise.all([loadPool(), loadSummary()]); }
  catch (e) { fail(e); }
}

// ---- журнал ------------------------------------------------------------------
function renderLog() {
  const box = $('#tab-log');
  let search = box.querySelector('input[type=search]');
  let pre = box.querySelector('pre');
  if (!pre) {
    search = el('input', { type: 'search', placeholder: 'фильтр: nodes, provision, ошибка…', value: S.logFilter, 'aria-label': 'Фильтр журнала' });
    search.addEventListener('input', () => { S.logFilter = search.value; renderLog(); });
    const again = el('button', { class: 'btn', type: 'button', onclick: () => loadLog().catch(fail) }, 'Обновить');
    pre = el('pre', { class: 'log mono', tabindex: '0', 'aria-label': 'Журнал {{BRAND}}' });
    box.replaceChildren(el('div', { class: 'bar' }, el('h2', {}, 'Журнал'), el('span', { class: 'grow' }), search, again),
      el('p', { class: 'hint' }, 'Последние строки {{BRAND}}: сверка, провижн, ядро на нодах, действия из этой страницы. Обновляется каждые 5 секунд.'), pre);
  }
  const f = S.logFilter.trim().toLowerCase();
  const lines = S.log.filter((l) => !f || l.line.toLowerCase().includes(f));
  const stick = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 30;
  pre.replaceChildren(...(lines.length ? lines.map((l) => el('div', {}, el('span', { class: 't' }, hhmmss(l.t) + '  '), l.line))
    : [el('span', { class: 'muted' }, f ? 'Ничего не нашлось.' : 'Пока пусто: строки появятся с первой сверкой.')]));
  if (stick) pre.scrollTop = pre.scrollHeight;
}

// ---- настройки ---------------------------------------------------------------
function renderSettings() {
  const box = $('#tab-settings');
  const st = S.settings;
  if (!st) { box.replaceChildren(el('div', { class: 'bar' }, el('h2', {}, 'Настройки')), el('p', { class: 'muted' }, 'Загружаю…')); return; }
  box.replaceChildren(el('div', { class: 'bar' }, el('h2', {}, 'Настройки')), squadsBlock(st), nameBlock(st), uaBlock(st));
  if (!S.squads && !S.squadsLoading && !S.squadsError) loadSquads();
}
async function loadSquads() {
  S.squadsLoading = true;
  try { S.squads = (await call('GET', BASE + '/squads')).squads; S.squadsError = null; }
  catch (e) { if (e instanceof AuthError) return fail(e); S.squadsError = e.message; }
  finally { S.squadsLoading = false; if (S.fillSquads) S.fillSquads(); }
}
function squadsBlock(st) {
  const cur = st.squads;
  const some = el('input', { type: 'radio', name: 'sq-mode', value: 'squads' });
  const all = el('input', { type: 'radio', name: 'sq-mode', value: 'all' });
  (cur.mode === 'all' ? all : some).checked = true;
  const list = el('div', { class: 'sqlist' });
  S.fillSquads = () => {
    if (S.squadsError) return list.replaceChildren(el('div', { class: 'err' }, S.squadsError));
    if (!S.squads) return list.replaceChildren(el('span', { class: 'muted' }, 'Загружаю сквады из Remnawave…'));
    if (!S.squads.length) return list.replaceChildren(el('span', { class: 'muted' }, 'В Remnawave нет сквадов.'));
    const sel = new Set(cur.squads);
    list.replaceChildren(...S.squads.map((q) => {
      const cb = el('input', { type: 'checkbox', value: q.uuid, 'data-name': q.name });
      cb.checked = sel.has(q.uuid) || sel.has(q.name);
      return el('label', { class: 'sq' }, cb, pill(q.name, 'c1'), q.members != null ? pill(q.members + ' юз.', 'c6') : '', el('span', { class: 'small mono' }, q.uuid));
    }));
  };
  S.fillSquads();
  const dim = () => list.classList.toggle('dim', all.checked);
  some.addEventListener('change', dim); all.addEventListener('change', dim); dim();
  const save = el('button', { class: 'btn primary', type: 'button' }, 'Сохранить');
  save.addEventListener('click', async () => {
    const mode = all.checked ? 'all' : 'squads';
    const boxes = [...list.querySelectorAll('input[type=checkbox]:checked')];
    if (mode === 'squads' && !boxes.length && !(await confirmBox('Никому не давать openflux?',
      'Ни один сквад не выбран: на ближайшей сверке каналы снимутся у всех юзеров.', 'Да, никому', true))) return;
    if (mode === 'all' && cur.mode !== 'all' && !(await confirmBox('Openflux всем активным юзерам?',
      'Канал заведётся каждому активному юзеру панели — на каждого свои доска и документ из пула.', 'Да, всем'))) return;
    try {
      S.settings = await call('PUT', BASE + '/settings', { squads: { mode, squads: boxes.map((b) => b.value), names: boxes.map((b) => b.dataset.name) } });
      toast('Сохранено: применится на ближайшей сверке — или нажми «Сверить сейчас»', 'good');
      renderSettings(); loadSummary().catch(() => {});
    } catch (e) { fail(e); }
  });
  const again = el('button', { class: 'btn', type: 'button' }, 'Обновить список');
  again.addEventListener('click', () => { S.squads = null; S.squadsError = null; S.fillSquads(); loadSquads(); });
  return el('div', { class: 'set' },
    el('h3', {}, 'Кому openflux'),
    el('p', { class: 'hint' }, 'Канал заводится юзеру, если его подписка активна и он хотя бы в одном из выбранных сквадов Remnawave. Сняли сквад — каналы его юзеров снимутся на сверке.'),
    el('label', { class: 'check' }, some, 'Юзерам выбранных сквадов'), list,
    el('label', { class: 'check' }, all, 'Всем активным юзерам панели'),
    cur.from === 'env' ? el('p', { class: 'note' }, 'Сейчас — из .env (TARGET_SQUADS' + (cur.mode === 'all' ? '=* — всем активным' : cur.squads.length ? ': ' + cur.squads.join(', ') : ' пуст — openflux никому, выбери сквады') + '). Сохранишь здесь — дальше будет отсюда.') : '',
    el('div', { class: 'bar' }, save, again));
}
function nameBlock(st) {
  const input = el('input', { type: 'text', maxlength: '64', placeholder: 'пусто — имя канала (u1a2b3c…)', value: st.link_name, spellcheck: 'false' });
  const node = (S.nodes && S.nodes[0] && S.nodes[0].name) || 'nl-1';
  const preview = el('span', {});
  const show = () => { const v = input.value.trim(); preview.replaceChildren(v ? pill(v.split('{node}').join(node), 'c5') : pill('u1a2b3c4d5e6f7a8b', 'muted')); };
  input.addEventListener('input', show); show();
  const save = el('button', { class: 'btn primary', type: 'button' }, 'Сохранить');
  save.addEventListener('click', async () => {
    try {
      S.settings = await call('PUT', BASE + '/settings', { link_name: input.value.trim() });
      toast('Имя сохранено: у юзеров — со следующим обновлением подписки', 'good'); loadSummary().catch(() => {});
    } catch (e) { fail(e); }
  });
  return el('div', { class: 'set' },
    el('h3', {}, 'Имя openflux в подписке'),
    el('p', { class: 'hint' }, 'Так профиль обхода называется в приложении. {node} — имя ноды канала. Меняется сразу у всех: имя переписывается в ссылке при выдаче подписки, каналы не пересоздаются.'),
    el('label', { class: 'f' }, el('span', {}, 'Имя'), input),
    el('div', { class: 'bar' }, el('span', { class: 'muted' }, 'В приложении будет:'), preview), el('div', { class: 'bar' }, save));
}
function uaBlock(st) {
  let list = st.ua_markers.slice();
  const pills = el('div', { class: 'bar' });
  const draw = () => pills.replaceChildren(...(list.length ? list.map((m) => {
    const x = el('button', { class: 'btn small', type: 'button', 'aria-label': 'Убрать ' + m, title: 'Убрать' }, '✕');
    x.addEventListener('click', () => { list = list.filter((v) => v !== m); draw(); });
    return el('span', { class: 'cellrow' }, pill(m, 'c2 mono'), x);
  }) : [el('span', { class: 'muted' }, 'никому — openflux не получит ни один клиент')]));
  draw();
  const input = el('input', { type: 'text', maxlength: '64', placeholder: 'например Rawline', spellcheck: 'false' });
  const add = el('button', { class: 'btn', type: 'button' }, 'Добавить');
  add.addEventListener('click', async () => {
    const v = input.value.trim();
    if (v.length < 2 || list.includes(v)) return;
    // метка, которую несёт обычный Happ («Happ», «Android»…), отдала бы openflux всем Happ
    if ('Happ/3.0 (Android) Happ/3.0 (iOS)'.includes(v) && !(await confirmBox('Метка «' + v + '»?',
      'Её содержит User-Agent обычного Happ: openflux получат все Happ, а не только ваш клиент.', 'Всё равно добавить', true))) return;
    list.push(v); input.value = ''; draw();
  });
  const save = el('button', { class: 'btn primary', type: 'button' }, 'Сохранить');
  save.addEventListener('click', async () => {
    try {
      S.settings = await call('PUT', BASE + '/settings', { ua_markers: list });
      toast('Клиенты сохранены — действует сразу', 'good'); renderSettings(); loadSummary().catch(() => {});
    } catch (e) { fail(e); }
  });
  return el('div', { class: 'set' },
    el('h3', {}, 'Клиенты, которым дописывать openflux'),
    el('p', { class: 'hint' }, 'openflux попадает в подписку, только если User-Agent приложения содержит одну из меток (с учётом регистра). Остальные — обычный Happ, v2rayNG, браузер — получают подписку как есть. Rawline шлёт «Happ/3.0 RawlineMobile/1.1.1 (Android)», поэтому метка — «Rawline», а не «Happ».'),
    pills, el('div', { class: 'bar' }, input, add), el('div', { class: 'bar' }, save));
}

// ---- вкладки, вход, таймеры -----------------------------------------------------
function showTab(tab) {
  if (!LOADERS[tab]) tab = 'nodes';
  S.tab = tab;
  document.querySelectorAll('.tabs button').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.tab === tab)));
  for (const t of Object.keys(LOADERS)) $('#tab-' + t).hidden = t !== tab;
  delete drawn[tab];
  ({ nodes: renderNodes, channels: renderChannels, pool: renderPool, log: renderLog, settings: renderSettings })[tab]();
  LOADERS[tab]().catch(fail);
  if (location.hash !== '#' + tab) history.replaceState(null, '', '#' + tab);
}
document.querySelectorAll('.tabs button').forEach((b) => b.addEventListener('click', () => showTab(b.dataset.tab)));
window.addEventListener('hashchange', () => { if (S.token && !$('#app').hidden) showTab(location.hash.slice(1)); });

let timers = [];
function startTimers() {
  stopTimers();
  timers.push(setInterval(() => { if (!document.hidden) refresh(); }, 20000));
  timers.push(setInterval(() => { if (!document.hidden && S.tab === 'log') loadLog().catch(fail); }, 5000));
}
function stopTimers() { timers.forEach(clearInterval); timers = []; }

function logout(msg) {
  stopTimers();
  S.token = '';
  try { sessionStorage.removeItem(KEY); localStorage.removeItem(KEY); } catch (e) {}
  $('#app').hidden = true;
  $('#login').hidden = false;
  const err = $('#login-err');
  err.textContent = msg || ''; err.hidden = !msg;
  $('#login-token').value = '';
  $('#login-token').focus();
}
async function enter() {
  await loadSummary();  // заодно проверка токена
  $('#login').hidden = true;
  $('#app').hidden = false;
  showTab((location.hash || '#nodes').slice(1));
  if (S.tab !== 'nodes') loadNodes().catch(fail);
  startTimers();
}
$('#logout').addEventListener('click', () => logout(''));
$('#login-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  S.token = $('#login-token').value.trim();
  try {
    await enter();
    const store = $('#login-remember').checked ? localStorage : sessionStorage;
    try { store.setItem(KEY, S.token); } catch (e) {}
  } catch (e) {
    S.token = '';
    const err = $('#login-err');
    err.textContent = e instanceof AuthError ? 'Токен не подошёл.' : e.message;
    err.hidden = false;
  }
});

(async () => {
  try { S.token = sessionStorage.getItem(KEY) || localStorage.getItem(KEY) || ''; } catch (e) { S.token = ''; }
  if (!S.token) return logout('');
  try { await enter(); } catch (e) { logout(e instanceof AuthError ? 'Сохранённый токен больше не подходит.' : e.message); }
})();
</script>
</body>
</html>
"""

PAGE = (_PAGE.replace("{{BRAND_HTML}}", f'<span class="b1">{BRAND[:3]}</span>{BRAND[3:]}')
        .replace("{{BRAND}}", BRAND)
        .replace("{{LOGO_TOP}}", logo("top"))
        .replace("{{LOGO_LOGIN}}", logo("login"))
        .replace("{{FAVICON}}", urllib.parse.quote(logo("ico"))))
