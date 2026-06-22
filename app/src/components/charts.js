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
  empty:   '#B45309',  
  emptyL:  '#FCD34D',  
  full:    '#1E3A8A',  
  fullL:   '#93C5FD', 
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

function apply(ref, option) {
  ref.lastOpt = option;
  if (ref.inst) {
    ref.inst.setOption(option, true);
    ref.inst.resize();
  } else if (ref.el && ref.el.clientWidth > 0 && ref.el.clientHeight > 0) {
    ref.inst = echarts.init(ref.el);
    ref.inst.setOption(option, true);
  }
}

async function loadAndRender() {
  const s = getState();
  await Promise.all([
    renderEvolFromAPI(s),
    loadRanking(s).then(() => { renderRank(); renderEmptySpain(); }),
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


const BANDS = [
  { label: '< 100',         min: 0,      max: 100,     vaciada: true  },
  { label: '100 – 500',     min: 100,    max: 500,     vaciada: true  },
  { label: '500 – 1 000',   min: 500,    max: 1000,    vaciada: true  },
  { label: '1 K – 5 K',     min: 1000,   max: 5000,    vaciada: false },
  { label: '5 K – 20 K',    min: 5000,   max: 20000,   vaciada: false },
  { label: '20 K – 100 K',  min: 20000,  max: 100000,  vaciada: false },
  { label: '> 100 K',       min: 100000, max: Infinity, vaciada: false },
];

function renderEmptySpain() {
  if (!lastRankings.length) {
    apply(charts.bands, emptyOption('Sin datos'));
    return;
  }

  const counts = new Array(BANDS.length).fill(0);
  const sums   = new Array(BANDS.length).fill(0);
  let totalMunis = 0;
  let totalPob   = 0;
  for (const r of lastRankings) {
    const i = BANDS.findIndex(b => r.valor >= b.min && r.valor < b.max);
    if (i < 0) continue;
    counts[i] += 1;
    sums[i]   += r.valor;
    totalMunis += 1;
    totalPob   += r.valor;
  }
  if (!totalMunis || !totalPob) {
    apply(charts.bands, emptyOption('Sin datos'));
    return;
  }

  const pctMunis  = counts.map(c => -(c / totalMunis * 100));
  const pctPob    = sums.map(s   =>  s / totalPob   * 100);
  const labels    = BANDS.map(b => b.label);

  const munisColors = BANDS.map(b => b.vaciada ? COLORS.empty : COLORS.emptyL);
  const pobColors   = BANDS.map(b => b.vaciada ? COLORS.fullL : COLORS.full);

  const vaciadosIdx = BANDS.map((b, i) => b.vaciada ? i : -1).filter(i => i >= 0);
  const munisVaciados = vaciadosIdx.reduce((a, i) => a + counts[i], 0);
  const pobVaciada    = vaciadosIdx.reduce((a, i) => a + sums[i],   0);
  const pctMunisVac   = munisVaciados / totalMunis * 100;
  const pctPobVac     = pobVaciada    / totalPob   * 100;

  const subtitle =
    `${pctMunisVac.toFixed(1)}% de municipios (< 1 000 hab) ` +
    `→ solo ${pctPobVac.toFixed(2)}% de la población`;

  apply(charts.bands, {
    title: {
      text: subtitle,
      left: 'center', top: 4,
      textStyle: { fontSize: 13, fontWeight: 600, color: '#0f172a' },
    },
    grid: { left: 110, right: 30, top: 60, bottom: 50, containLabel: false },
    legend: {
      bottom: 4,
      icon: 'roundRect',
      textStyle: { fontSize: 12 },
      data: [
        { name: '% de municipios', itemStyle: { color: COLORS.empty } },
        { name: '% de población',  itemStyle: { color: COLORS.full  } },
      ],
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const idx = params[0].dataIndex;
        const m = counts[idx];
        const p = sums[idx];
        const mp = (m / totalMunis * 100);
        const pp = (p / totalPob   * 100);
        return `
          <strong>${BANDS[idx].label} hab.</strong><br>
          Municipios: <b>${formatCompact(m)}</b> (${mp.toFixed(1)}%)<br>
          Población:  <b>${formatCompact(p)}</b> (${pp.toFixed(2)}%)
        `;
      },
    },
    xAxis: {
      type: 'value',
      position: 'top',
      axisLabel: {
        fontSize: 11,
        formatter: v => Math.abs(v).toFixed(0) + '%',
      },
      splitLine: { lineStyle: { color: '#e2e8f0' } },
      min: (val) => -Math.max(Math.abs(val.min), val.max),
      max: (val) =>  Math.max(Math.abs(val.min), val.max),
    },
    yAxis: {
      type: 'category',
      data: labels,
      inverse: true,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#cbd5e1' } },
      axisLabel: { fontSize: 12, fontWeight: 500 },
    },
    series: [
      {
        name: '% de municipios',
        type: 'bar',
        stack: 'lado',
        data: pctMunis.map((v, i) => ({
          value: v,
          itemStyle: { color: munisColors[i], borderRadius: [4, 0, 0, 4] },
        })),
        label: {
          show: true,
          position: 'left',
          fontSize: 11,
          fontWeight: 600,
          color: '#475569',
          formatter: p => formatCompact(counts[p.dataIndex]) +
                          ' (' + Math.abs(p.value).toFixed(1) + '%)',
        },
        barWidth: '62%',
      },
      {
        name: '% de población',
        type: 'bar',
        stack: 'lado',
        data: pctPob.map((v, i) => ({
          value: v,
          itemStyle: { color: pobColors[i], borderRadius: [0, 4, 4, 0] },
        })),
        label: {
          show: true,
          position: 'right',
          fontSize: 11,
          fontWeight: 600,
          color: '#475569',
          formatter: p => formatCompact(sums[p.dataIndex]) +
                          ' (' + p.value.toFixed(2) + '%)',
        },
        barWidth: '62%',
      },
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

  const bandsMeta = document.querySelector('#view-graficos .card--wide .card__meta');
  if (bandsMeta) {
    bandsMeta.textContent = 'Municipios vs. población que albergan, por tamaño · ' + scope;
  }
  const bandsTitle = document.querySelector('#view-graficos .card--wide .card__title');
  if (bandsTitle && bandsTitle.textContent !== 'España vaciada') {
    bandsTitle.textContent = 'España vaciada';
  }
}