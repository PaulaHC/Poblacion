import { getState, setState, subscribe } from '../state/store.js';
import { API_BASE } from '../config.js';
import { formatCompact, formatNumber } from '../utils/format.js';
import { debounce } from '../utils/debounce.js';
import { escapeHtml } from '../utils/html.js';

let lastRanking = [];
let sortKey  = 'valor';
let sortDir  = 'desc';

export function mountStats() {
  const refresh = debounce(loadAndRender, 250);
  subscribe(refresh);

  // Sorting de columnas
  const table = document.getElementById('stats-table');
  if (table) {
    table.querySelectorAll('thead th').forEach(th => {
      th.addEventListener('click', () => {
        const k = th.dataset.key;
        if (!k) return;
        if (sortKey === k) sortDir = (sortDir === 'asc' ? 'desc' : 'asc');
        else { sortKey = k; sortDir = th.dataset.num ? 'desc' : 'asc'; }
        markSortedHeader();
        renderTable();
      });
    });
  }

  loadAndRender();
}

async function loadAndRender() {
  const s = getState();
  await Promise.all([
    loadKpis(s),
    loadRanking(s).then(renderTable),
  ]);
}

/* ---------------- KPIs ---------------- */
async function loadKpis(s) {
  const url = buildUrl('/stats', {
    anio: s.anio,
    comunidad: s.comunidad, provincia: s.provincia, municipio: s.municipio,
  });
  let data;
  try {
    data = await (await fetch(url)).json();
  } catch (e) { console.error('[stats] kpis', e); return; }
  renderKpis(data, s);
}

function renderKpis(d, s) {
  const wrap = document.getElementById('kpis');
  if (!wrap || !d) return;

  // Densidad: solo si es un municipio único y conocemos superficie del INE.
  // Como ahora mismo no la tenemos cacheada, mostramos N/D explicando.
  const densidad = null;

  const deltaCls = (d.delta_pct == null) ? '' : (d.delta_pct >= 0 ? 'kpi--up' : 'kpi--down');
  const deltaTxt = (d.delta_pct == null)
    ? '—'
    : (d.delta_pct >= 0 ? '↑ ' : '↓ ') + Math.abs(d.delta_pct).toFixed(2) + '%';
  const deltaAbs = (d.delta == null) ? ''
    : ((d.delta >= 0 ? '+' : '') + formatCompact(d.delta) + ' hab. vs ' + (s.anio - 1));

  const masc = (d.indice_masc == null) ? '—' : d.indice_masc.toFixed(1);
  const mascHint = (d.indice_masc == null)
    ? 'sin datos por sexo'
    : (d.indice_masc < 100
        ? 'menos hombres que mujeres'
        : 'más hombres que mujeres');

  wrap.innerHTML = `
    ${kpiCard({
      label: 'Población total',
      value: formatNumber(d.poblacion_total),
      hint:  `${formatCompact(d.num_municipios)} municipios · año ${s.anio}`,
    })}
    ${kpiCard({
      label: 'Variación interanual',
      value: deltaTxt,
      hint:  deltaAbs,
      cls:   deltaCls,
    })}
    ${kpiCard({
      label: 'Densidad',
      value: densidad ? densidad.toFixed(1) + ' hab/km²' : 'N/D',
      hint:  densidad ? '' : 'pendiente de datos de superficie',
    })}
    ${kpiCard({
      label: 'Índice de masculinidad',
      value: masc,
      hint:  mascHint,
    })}
  `;
}

function kpiCard({ label, value, hint, cls = '' }) {
  return `
    <div class="kpi ${cls}">
      <div class="kpi__label">${escapeHtml(label)}</div>
      <div class="kpi__value">${escapeHtml(value)}</div>
      <div class="kpi__hint">${escapeHtml(hint || '')}</div>
    </div>
  `;
}

/* ---------------- Tabla ---------------- */
async function loadRanking(s) {
  const url = buildUrl('/ranking', {
    anio: s.anio, sexo: s.sexo,
    comunidad: s.comunidad, provincia: s.provincia,
  });
  try {
    lastRanking = await (await fetch(url)).json() || [];
  } catch (e) {
    console.error('[stats] ranking', e); lastRanking = [];
  }
  return lastRanking;
}

function renderTable() {
  const tbody = document.querySelector('#stats-table tbody');
  if (!tbody) return;

  // Preparar filas con delta y delta%
  const rows = lastRanking.map(r => {
    const delta = (r.prev != null) ? (r.valor - r.prev) : null;
    const deltap = (r.prev && r.prev > 0) ? (delta / r.prev * 100) : null;
    return { ...r, delta, deltap };
  });

  // Ordenar
  rows.sort((a, b) => cmp(a[sortKey], b[sortKey], sortDir));

  // Limitar a 200 (la tabla seguiría siendo navegable con scroll)
  const TOP = rows.slice(0, 200);

  tbody.innerHTML = TOP.map(r => {
    const dCls = r.delta == null ? '' : (r.delta >= 0 ? 'tr-up' : 'tr-down');
    const dTxt = r.delta  == null ? '—' : ((r.delta  >= 0 ? '+' : '') + formatCompact(r.delta));
    const pTxt = r.deltap == null ? '—' : ((r.deltap >= 0 ? '+' : '') + r.deltap.toFixed(2) + '%');
    const prev = r.prev   == null ? '—' : formatNumber(r.prev);
    return `
      <tr data-cod="${escapeHtml(r.cod_municipio)}" class="${dCls}">
        <td class="td-name">${escapeHtml(r.nombre || '')}</td>
        <td class="td-mono">${escapeHtml(r.cod_provincia || '')}</td>
        <td class="td-num">${formatNumber(r.valor)}</td>
        <td class="td-num">${prev}</td>
        <td class="td-num">${dTxt}</td>
        <td class="td-num">${pTxt}</td>
      </tr>
    `;
  }).join('');

  // Click en fila → enfocar municipio en el store
  tbody.querySelectorAll('tr').forEach(tr => {
    tr.addEventListener('click', () => {
      const cod = tr.dataset.cod;
      if (cod) setState({ municipio: cod });
    });
  });

  const meta = document.getElementById('stats-table-meta');
  if (meta) meta.textContent = `${rows.length} municipios · mostrando primeros ${TOP.length}`;
}

function markSortedHeader() {
  document.querySelectorAll('#stats-table thead th').forEach(th => {
    th.classList.remove('is-sorted', 'asc', 'desc');
    if (th.dataset.key === sortKey) {
      th.classList.add('is-sorted', sortDir);
    }
  });
}

function cmp(a, b, dir) {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  let r;
  if (typeof a === 'number' && typeof b === 'number') r = a - b;
  else r = String(a).localeCompare(String(b), 'es', { numeric: true });
  return dir === 'asc' ? r : -r;
}

function buildUrl(path, params) {
  const url = new URL(API_BASE + path, window.location.origin);
  for (const [k, v] of Object.entries(params)) {
    if (v != null && v !== '') url.searchParams.set(k, v);
  }
  return url.toString();
}