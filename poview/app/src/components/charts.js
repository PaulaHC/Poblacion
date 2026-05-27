import { getState, subscribe } from '../state/store.js';
import { API_BASE } from '../config.js';
import { formatCompact } from '../utils/format.js';
import { debounce } from '../utils/debounce.js';

const COLORS = {
  total:   '#1E3A8A',
  hombres: '#3B82F6',
  mujeres: '#EC4899',
  bar:     '#2563EB',
  bar2:    '#94A3B8',
  up:      '#16A34A',
  down:    '#DC2626',
};

const charts = {
  evol:  { el: null, inst: null, lastOpt: null },
  rank:  { el: null, inst: null, lastOpt: null },
  bands: { el: null, inst: null, lastOpt: null },
};

let lastRankings = [];
let rankMode = 'poblacion';

export function mountCharts() {
  charts.evol.el  = document.getElementById('chart-evol');
  charts.rank.el  = document.getElementById('chart-rank');
  charts.bands.el = document.getElementById('chart-bands');
  if (!charts.evol.el || !charts.rank.el || !charts.bands.el) return;

  const ro = new ResizeObserver(entries => {
    for (const e of entries) {
      const el = e.target;
      const w = el.clientWidth, h = el.clientHeight;
      if (w === 0 || h === 0) continue;
      const ref = findRef(el);
      if (!ref) continue;
      if (!ref.inst) {
        ref.inst = echarts.init(el);
      } else {
        ref.inst.resize();
      }
      if (ref.lastOpt) ref.inst.setOption(ref.lastOpt, true);
    }
  });
  ro.observe(charts.evol.el);
  ro.observe(charts.rank.el);
  ro.observe(charts.bands.el);

  // Toggle de modo del ranking
  document.querySelectorAll('.seg-mini__btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.seg-mini__btn').forEach(b => b.classList.remove('is-active'));
      btn.classList.add('is-active');
      rankMode = btn.dataset.rank;
      renderRank();
    });
  });

  // Reaccionar a cambios de filtros
  const refresh = debounce(loadAndRender, 250);
  subscribe(refresh);

  window.addEventListener('resize', () => {
    for (const c of Object.values(charts)) c.inst && c.inst.resize();
  });

  loadAndRender();
}

function findRef(el) {
  if (el === charts.evol.el)  return charts.evol;
  if (el === charts.rank.el)  return charts.rank;
  if (el === charts.bands.el) return charts.bands;
  return null;
}

/** Aplica una opción al chart: si el chart todavía no se inicializó
 *  (porque su contenedor está oculto), guarda la opción y se aplicará
 *  cuando el ResizeObserver detecte tamaño. */
function apply(ref, option) {
  ref.lastOpt = option;
  if (ref.inst) {
    ref.inst.setOption(option, true);
    ref.inst.resize();
  } else if (ref.el && ref.el.clientWidth > 0 && ref.el.clientHeight > 0) {
    ref.inst = echarts.init(ref.el);
    ref.inst.setOption(option, true);
  }
  // si no, esperamos al observer.
}

async function loadAndRender() {
  const s = getState();
  await Promise.all([
    renderEvolFromAPI(s),
    loadRanking(s).then(() => { renderRank(); renderBands(); }),
  ]);
  updateMeta(s);
}

/* ---------------- 1. Evolución temporal ---------------- */
async function renderEvolFromAPI(s) {
  const url = buildUrl('/serie', {
    comunidad: s.comunidad, provincia: s.provincia, municipio: s.municipio,
  });
  let data;
  try {
    data = await (await fetch(url)).json();
  } catch (e) { console.error('[charts] serie', e); return; }

  let opt;
  if (!data || !data.anios || !data.anios.length) {
    opt = emptyOption('Sin datos para este ámbito');
  } else {
    opt = {
      grid: { left: 56, right: 24, top: 50, bottom: 36 },
      legend: { top: 8, icon: 'circle', textStyle: { fontSize: 12 } },
      tooltip: {
        trigger: 'axis',
        valueFormatter: v => formatCompact(v) + ' hab.',
        axisPointer: { type: 'line' },
      },
      xAxis: {
        type: 'category', data: data.anios,
        axisLabel: { fontSize: 11 },
        axisLine: { lineStyle: { color: '#cbd5e1' } },
      },
      yAxis: {
        type: 'value',
        axisLabel: { fontSize: 11, formatter: formatCompact },
        splitLine: { lineStyle: { color: '#e2e8f0' } },
      },
      series: [
        lineSeries('Total',   data.total,   COLORS.total,   true),
        lineSeries('Hombres', data.hombres, COLORS.hombres, false),
        lineSeries('Mujeres', data.mujeres, COLORS.mujeres, false),
      ],
    };
  }
  apply(charts.evol, opt);
}

function lineSeries(name, data, color, area) {
  return {
    name, type: 'line', smooth: true, showSymbol: false,
    lineStyle: { width: 2.2, color },
    itemStyle: { color },
    areaStyle: area ? {
      color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
        colorStops: [
          { offset: 0, color: color + '40' },
          { offset: 1, color: color + '00' },
        ]}} : undefined,
    data,
  };
}

/* ---------------- 2. Ranking ---------------- */
async function loadRanking(s) {
  const url = buildUrl('/ranking', {
    anio: s.anio, sexo: s.sexo, comunidad: s.comunidad, provincia: s.provincia,
  });
  try {
    lastRankings = await (await fetch(url)).json() || [];
  } catch (e) {
    console.error('[charts] ranking', e); lastRankings = [];
  }
  return lastRankings;
}

function renderRank() {
  if (!lastRankings.length) {
    apply(charts.rank, emptyOption('Sin datos'));
    return;
  }

  let rows, labelFmt, title;
  if (rankMode === 'poblacion') {
    rows = [...lastRankings].sort((a, b) => b.valor - a.valor).slice(0, 10);
    labelFmt = v => formatCompact(v);
    title = 'Población absoluta';
  } else {
    rows = lastRankings
      .filter(r => r.prev && r.prev > 50)
      .map(r => ({ ...r, pct: (r.valor - r.prev) / r.prev * 100 }))
      .sort((a, b) => b.pct - a.pct)
      .slice(0, 10);
    labelFmt = v => (v >= 0 ? '+' : '') + v.toFixed(1) + '%';
    title = 'Variación interanual %';
  }

  const data    = rows.map(r => rankMode === 'poblacion' ? r.valor : r.pct);
  const labels  = rows.map(r => r.nombre);
  const colorFn = (rankMode === 'poblacion')
    ? () => COLORS.bar
    : (params) => params.value >= 0 ? COLORS.up : COLORS.down;

  apply(charts.rank, {
    grid: { left: 130, right: 30, top: 30, bottom: 24 },
    tooltip: { trigger: 'axis', valueFormatter: labelFmt },
    xAxis: {
      type: 'value',
      axisLabel: { fontSize: 11, formatter: labelFmt },
      splitLine: { lineStyle: { color: '#e2e8f0' } },
    },
    yAxis: {
      type: 'category', data: labels.reverse(),
      axisLabel: { fontSize: 11 },
      axisLine: { lineStyle: { color: '#cbd5e1' } },
    },
    series: [{
      name: title,
      type: 'bar',
      data: data.reverse(),
      itemStyle: { color: colorFn, borderRadius: [0, 4, 4, 0] },
      label: { show: true, position: 'right', fontSize: 11,
               formatter: p => labelFmt(p.value) },
    }],
  });
}

/* ---------------- 3. Distribución por tamaño ---------------- */
const BANDS = [
  { label: '< 100',         min: 0,      max: 100      },
  { label: '100 – 500',     min: 100,    max: 500      },
  { label: '500 – 2 000',   min: 500,    max: 2000     },
  { label: '2 K – 10 K',    min: 2000,   max: 10000    },
  { label: '10 K – 50 K',   min: 10000,  max: 50000    },
  { label: '50 K – 250 K',  min: 50000,  max: 250000   },
  { label: '> 250 K',       min: 250000, max: Infinity },
];

function renderBands() {
  if (!lastRankings.length) {
    apply(charts.bands, emptyOption('Sin datos'));
    return;
  }

  const counts = new Array(BANDS.length).fill(0);
  const sums   = new Array(BANDS.length).fill(0);
  for (const r of lastRankings) {
    const i = BANDS.findIndex(b => r.valor >= b.min && r.valor < b.max);
    if (i >= 0) { counts[i]++; sums[i] += r.valor; }
  }
  const labels = BANDS.map(b => b.label);

  apply(charts.bands, {
    grid: { left: 56, right: 56, top: 50, bottom: 36 },
    legend: { top: 8, icon: 'roundRect', textStyle: { fontSize: 12 } },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: {
      type: 'category', data: labels,
      axisLabel: { fontSize: 11 },
      axisLine: { lineStyle: { color: '#cbd5e1' } },
    },
    yAxis: [
      { type: 'value', name: 'nº municipios',
        axisLabel: { fontSize: 11 },
        splitLine: { lineStyle: { color: '#e2e8f0' } } },
      { type: 'value', name: 'población',
        axisLabel: { fontSize: 11, formatter: formatCompact },
        splitLine: { show: false } },
    ],
    series: [
      { name: 'Nº municipios', type: 'bar', data: counts,
        itemStyle: { color: COLORS.bar2, borderRadius: [4, 4, 0, 0] },
        barWidth: '36%' },
      { name: 'Población',     type: 'bar', data: sums, yAxisIndex: 1,
        itemStyle: { color: COLORS.bar,  borderRadius: [4, 4, 0, 0] },
        barWidth: '36%' },
    ],
  });
}

/* ---------------- Helpers ---------------- */
function buildUrl(path, params) {
  const url = new URL(API_BASE + path, window.location.origin);
  for (const [k, v] of Object.entries(params)) {
    if (v != null && v !== '') url.searchParams.set(k, v);
  }
  return url.toString();
}

function emptyOption(text) {
  return {
    title: {
      text, left: 'center', top: 'middle',
      textStyle: { color: '#94a3b8', fontSize: 13, fontWeight: 'normal' },
    },
    xAxis: { show: false }, yAxis: { show: false },
  };
}

function updateMeta(s) {
  const el = document.getElementById('chart-evol-meta');
  if (!el) return;
  let scope = 'España';
  if (s.municipio) scope = 'Municipio ' + s.municipio;
  else if (s.provincia) scope = 'Provincia ' + s.provincia;
  else if (s.comunidad) scope = s.comunidad;
  el.textContent = `Población por sexo · ${scope} · 1996–${s.anio}`;
}