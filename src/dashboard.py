from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _js_data(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</script>", r"<\/script>")


def build_dashboard(
    leads: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    output_path: Path,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    page = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>I’MON — Search Orders</title>
<style>
:root { color-scheme: dark; font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; background: #0b0d10; color: #f5f7fa; }
main { max-width: 1280px; margin: 0 auto; padding: 34px 24px 80px; }
h1 { font-size: 34px; margin: 0 0 8px; }
.sub { color: #9ca7b7; margin-bottom: 26px; }
.controls { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:20px; }
button, .link { border:0; border-radius:12px; padding:10px 14px; font-weight:650; cursor:pointer; text-decoration:none; }
.tab { background:#1b2028; color:#dce3ec; }
.tab.active { background:#f5f7fa; color:#11151a; }
.grid { display:grid; gap:14px; }
.card { background:#14181e; border:1px solid #242b35; border-radius:18px; padding:18px; }
.card[data-status="work"] { border-color:#55d187; }
.card[data-status="skip"] { opacity:.48; }
.topline { display:flex; justify-content:space-between; gap:14px; align-items:flex-start; }
.score { min-width:74px; text-align:center; font-size:13px; font-weight:800; background:#222935; border-radius:12px; padding:8px; line-height:1.25; }
.section { margin-top:12px; padding-top:10px; border-top:1px solid #242b35; }
.section b { color:#f4f7fb; display:block; margin-bottom:5px; }
.good { color:#8ce6ad; }
.risk { color:#ffb4a8; }
.meta { color:#9ca7b7; font-size:13px; margin:7px 0; }
.title { font-size:19px; font-weight:750; line-height:1.3; }
.company { font-size:15px; color:#d9e0e9; margin-top:5px; }
.details { color:#b7c0cc; margin:12px 0; line-height:1.45; font-size:14px; }
.actions { display:flex; gap:8px; flex-wrap:wrap; margin-top:14px; }
.work { background:#55d187; color:#07130c; }
.skip { background:#2b313b; color:#d6dce5; }
.link { background:#2684ff; color:white; display:inline-block; }
.badge { display:inline-block; padding:4px 8px; border-radius:999px; background:#232a34; margin-right:6px; }
.empty { padding:26px; color:#9ca7b7; border:1px dashed #343c47; border-radius:16px; }
</style>
</head>
<body>
<main>
  <h1>I’MON Search Orders</h1>
  <div class="sub">Зарубежные лиды без тендеров: прямой спрос, агентства-партнёры и компании с buying signals. Метод: гипотеза → проверка → критика → вывод.</div>
  <div class="controls">
    <button id="tab-leads" class="tab active" onclick="showTab('leads')">Проверенные лиды <span id="count-leads"></span></button>
    <button id="tab-signals" class="tab" onclick="showTab('signals')">Новые сигналы <span id="count-signals"></span></button>
    <button class="tab" onclick="showOnly('all')">Все</button>
    <button class="tab" onclick="showOnly('work')">В работе</button>
    <button class="tab" onclick="showOnly('new')">Новые</button>
  </div>
  <div id="grid" class="grid"></div>
</main>
<script>
const leads = __LEADS_JSON__;
const signals = __SIGNALS_JSON__;
let currentTab = 'leads';
let currentFilter = 'all';
const storageKey = 'searchordersStatus.v1';
const countryRu = {DEU:'Германия', NLD:'Нидерланды', GBR:'Великобритания', USA:'США', CHE:'Швейцария'};
const serviceRu = {branding:'Брендинг', presentations:'Презентации', web:'Веб', ux_ui:'UX/UI', creative:'Графический дизайн'};
const signalRu = {funding:'Финансирование', rebrand:'Ребрендинг', expansion:'Расширение'};
const conclusionRu = {strong:'СИЛЬНЫЙ', verify_more:'ПРОВЕРИТЬ', reject:'ОТКЛОНИТЬ'};
const channelRu = {direct_outbound:'Прямой outbound', agency_partners:'Агентство / партнёр', events_launches:'Событие / запуск'};

function reasonRu(value) {
  const s = String(value || '');
  if (s.startsWith('international/global remote explicitly allowed')) return 'международные кандидаты / global remote разрешены' + s.slice(s.lastIndexOf(' ('));
  if (s.startsWith('remote work supported')) return 'удалённая работа поддерживается' + s.slice(s.lastIndexOf(' ('));
  if (s.startsWith('agency/white-label collaboration explicitly supported')) return 'агентства / white-label партнёры разрешены' + s.slice(s.lastIndexOf(' ('));
  if (s.startsWith('country/local-only restriction')) return 'ограничение по стране / только локальные кандидаты' + s.slice(s.lastIndexOf(' ('));
  if (s.startsWith('local candidates preferred')) return 'предпочтение локальным кандидатам' + s.slice(s.lastIndexOf(' ('));
  if (s.startsWith('onsite/studio presence requested')) return 'требуется присутствие onsite / в студии' + s.slice(s.lastIndexOf(' ('));
  if (s.startsWith('role is oriented to an individual contractor')) return 'роль ориентирована на отдельного исполнителя' + s.slice(s.lastIndexOf(' ('));
  if (s.startsWith('text service match:')) return 'совпадение по услугам' + s.slice(s.lastIndexOf(' ('));
  if (s.startsWith('primary graphic/web CPV:')) return 'основной CPV — графический/веб-дизайн' + s.slice(s.lastIndexOf(' ('));
  if (s.startsWith('additional design/web CPV backed by text match:')) return 'дополнительный CPV дизайна подтверждён текстом' + s.slice(s.lastIndexOf(' ('));
  if (s.startsWith('broad CPV backed by text match:')) return 'широкий CPV подтверждён текстом' + s.slice(s.lastIndexOf(' ('));
  if (s === 'target market (+10)') return 'целевой рынок (+10)';
  if (s === 'published within 3 days (+15)') return 'опубликовано за последние 3 дня (+15)';
  if (s === 'published within 7 days (+10)') return 'опубликовано за последние 7 дней (+10)';
  if (s === 'recent lead (+5)') return 'свежий лид (+5)';
  if (s === 'declared value >= 50k (+15)') return 'заявленный бюджет от 50 тыс. (+15)';
  if (s === 'declared value >= 10k (+10)') return 'заявленный бюджет от 10 тыс. (+10)';
  if (s === 'declared value >= 3k (+5)') return 'заявленный бюджет от 3 тыс. (+5)';
  if (s === 'at least 14 days to respond (+10)') return 'до дедлайна минимум 14 дней (+10)';
  if (s === 'at least 5 days to respond (+5)') return 'до дедлайна минимум 5 дней (+5)';
  if (s === 'direct source URL (+5)') return 'есть прямая ссылка на источник (+5)';
  if (s === 'official procurement source (+5)') return 'официальный источник закупки (+5)';
  return s;
}

function loadStatuses() {
  try { return JSON.parse(localStorage.getItem(storageKey) || '{}'); } catch (_) { return {}; }
}
function saveStatuses(value) { localStorage.setItem(storageKey, JSON.stringify(value)); }
function setStatus(id, status) {
  const s = loadStatuses();
  if (status === 'new') delete s[id]; else s[id] = status;
  saveStatuses(s);
  render();
}
function money(v, c) {
  if (v === null || v === undefined || v === '') return '';
  const n = Number(v);
  if (Number.isNaN(n)) return String(v) + ' ' + (c || '');
  return new Intl.NumberFormat('ru-RU', {maximumFractionDigits:0}).format(n) + ' ' + (c || '');
}
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function showTab(tab) {
  currentTab = tab;
  document.getElementById('tab-leads').classList.toggle('active', tab === 'leads');
  document.getElementById('tab-signals').classList.toggle('active', tab === 'signals');
  render();
}
function showOnly(filter) { currentFilter = filter; render(); }
function render() {
  const statuses = loadStatuses();
  const data = currentTab === 'leads' ? leads : signals;
  const filtered = data.filter(item => {
    const status = statuses[item.id] || 'new';
    return currentFilter === 'all' || status === currentFilter;
  });
  document.getElementById('count-leads').textContent = '(' + leads.length + ')';
  document.getElementById('count-signals').textContent = '(' + signals.length + ')';
  const grid = document.getElementById('grid');
  if (!filtered.length) {
    grid.innerHTML = '<div class="empty">Здесь пока ничего нет.</div>';
    return;
  }
  grid.innerHTML = filtered.map(item => {
    const status = statuses[item.id] || 'new';
    const isSignal = Boolean(item.signal_type) && !item.conclusion;
    const company = isSignal ? (item.company_guess || 'Компания требует уточнения') : (item.company || 'Компания не указана');
    const detailParts = [];
    if (item.country) detailParts.push(countryRu[item.country] || item.country);
    if (item.channel) detailParts.push(channelRu[item.channel] || item.channel);
    if (item.published_at) detailParts.push('Сигнал/публикация: ' + item.published_at);
    if (item.deadline) detailParts.push('Дедлайн: ' + item.deadline);
    const budget = money(item.value, item.currency);
    if (budget) detailParts.push('Бюджет/ставка: ' + budget);
    if (isSignal && item.signal_type) detailParts.push('Сигнал: ' + (signalRu[item.signal_type] || item.signal_type));
    const serviceBadges = (item.services || []).map(s => '<span class="badge">' + esc(serviceRu[s] || s) + '</span>').join('');
    const evidence = (item.evidence || []).map(x => '• ' + esc(x)).join('<br>');
    const counter = (item.counter_evidence || []).map(x => '• ' + esc(x)).join('<br>');
    const fitReasons = (item.fit_reasons || []).map(x => '• ' + esc(reasonRu(x))).join('<br>');
    const fitScore = item.fit_score ?? item.score ?? item.confidence ?? 0;
    const fitBase = item.base_confidence ?? item.confidence ?? item.score ?? 0;
    const fitAdjustment = item.fit_adjustment ?? 0;
    const fitClass = fitAdjustment < 0 ? 'risk' : 'good';
    const ia5 = item.conclusion ? `
      <div class="section ${fitClass}"><b>Fit для I’MON</b>${esc(fitBase)} → <strong>${esc(fitScore)}</strong> (${fitAdjustment >= 0 ? '+' : ''}${esc(fitAdjustment)})<br>${fitReasons || 'Географические/форматные ограничения не выявлены'}</div>
      <div class="section"><b>Почему может быть клиент</b>${esc(item.hypothesis || '')}</div>
      <div class="section good"><b>Что подтверждено</b>${evidence || 'Пока нет подтверждений'}</div>
      <div class="section risk"><b>Что вызывает сомнение</b>${counter || 'Явных контраргументов пока нет'}</div>
      <div class="section"><b>Что предлагаем</b>${esc(item.proposed_service || '')}</div>
      <div class="section"><b>Кому писать</b>${esc(item.decision_maker_role || 'Нужно определить')}</div>
      <div class="section"><b>Как заходить</b>${esc(item.outreach_angle || '')}</div>
    ` : '';
    const description = isSignal ? (item.summary_ru || item.summary || '') : '';
    return `
      <article class="card" data-status="${esc(status)}">
        <div class="topline">
          <div>
            <div class="meta">${esc(item.source || '')}</div>
            <div class="title">${esc(item.title_ru || item.title || '')}</div>
            <div class="company">${esc(company)}</div>
          </div>
          <div class="score">${item.conclusion ? esc(conclusionRu[item.conclusion] || item.conclusion) + '<br>FIT ' + esc(fitScore) : esc(item.score || 0)}</div>
        </div>
        <div class="meta">${esc(detailParts.join(' · '))}</div>
        <div>${serviceBadges}</div>
        <div class="details">${esc(description)}</div>
        ${ia5}
        <div class="actions">
          <button class="work" onclick="setStatus('${esc(item.id)}','work')">В работу</button>
          <button class="skip" onclick="setStatus('${esc(item.id)}','skip')">Пропустить</button>
          <button class="skip" onclick="setStatus('${esc(item.id)}','new')">Сбросить</button>
          <a class="link" href="${esc(item.url || '#')}" target="_blank" rel="noopener">Источник</a>
        </div>
      </article>`;
  }).join('');
}
render();
</script>
</body>
</html>"""

    page = page.replace("__LEADS_JSON__", _js_data(leads))
    page = page.replace("__SIGNALS_JSON__", _js_data(signals))
    output_path.write_text(page, encoding="utf-8")
    return output_path
