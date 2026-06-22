import {
  API_BASE, MAP_CONFIG, LAYER_STYLE, CIRCLE_RADIUS, SECTOR_ICONS,
} from '../config.js';
import { getState, subscribe } from '../state/store.js';
import { sizeScale } from '../utils/color-scale.js';
import { formatCompact } from '../utils/format.js';
import { debounce } from '../utils/debounce.js';
import { loadGeoJson } from '../api/geo.js';
import { renderLegendBlock, removeLegendBlock } from './legend.js';
import {
  getMapInstance, getCentroid, isCodeInScope, setBaseVisible,
  whenMapReady, setTooltipProvider,
} from './map.js';

const MODOS = ['poblacion', 'renta', 'trabajo', 'estudios'];
const LABELS = { poblacion: 'Población', renta: 'Renta', trabajo: 'Trabajo', estudios: 'Estudios' };

const overlays = {
  renta:    { layer: null, renderer: null, data: null, byId: null, nivel: null },
  trabajo:  { layer: null, renderer: null, data: null, byId: null, nivel: null },
  estudios: { layer: null, renderer: null, data: null, byId: null, nivel: null },
};
const activos = new Set(['poblacion']);
let legendEl = null;
let provCentroids = null;

export async function mountLayers() {
  const map = getMapInstance();
  if (!map) { console.error('[layers] mapa no disponible'); return; }
  legendEl = document.getElementById('map-legend');

  addControl(map);
  overlays.renta.renderer    = L.canvas({ pane: 'pane-renta' });
  overlays.estudios.renderer = L.canvas({ pane: 'pane-estudios' });
  overlays.trabajo.renderer  = L.canvas({ pane: 'pane-trabajo' });

  setTooltipProvider(overlayRows);


  const onChange = debounce((s, changed) => {
    if (!changed.some(k => ['anio', 'comunidad', 'provincia', 'municipio'].includes(k))) return;
    for (const modo of ['renta', 'trabajo', 'estudios']) {
      if (activos.has(modo)) refrescarModo(modo);
    }
  }, 200);
  subscribe(onChange);

  await whenMapReady();
}

/* ------------------------------------------------------------ Panel */
function addControl(map) {
  const Control = L.Control.extend({
    options: { position: 'topright' },
    onAdd() {
      const div = L.DomUtil.create('div', 'layer-control');
      div.innerHTML = `
        <div class="layer-control__title">Capas</div>
        ${MODOS.map(m => `
          <label class="layer-control__row">
            <input type="checkbox" data-modo="${m}" ${m === 'poblacion' ? 'checked' : ''}>
            <span>${LABELS[m]}</span>
          </label>`).join('')}
        <div class="layer-control__hint" id="layer-hint"></div>`;
      L.DomEvent.disableClickPropagation(div);
      L.DomEvent.disableScrollPropagation(div);
      div.querySelectorAll('input[type="checkbox"]').forEach(inp => {
        inp.addEventListener('change', () => toggleModo(inp.dataset.modo, inp.checked));
      });
      return div;
    },
  });
  map.addControl(new Control());
}

function setHint(text) {
  const el = document.getElementById('layer-hint');
  if (el) el.textContent = text || '';
}

/* ------------------------------------------------------------ Toggle */
function toggleModo(modo, on) {
  if (on) activos.add(modo); else activos.delete(modo);
  if (modo === 'poblacion') { setBaseVisible(on); return; }
  if (on) refrescarModo(modo);
  else desmontarModo(modo);
}

function desmontarModo(modo) {
  const o = overlays[modo];
  if (o.layer) { getMapInstance().removeLayer(o.layer); o.layer = null; }
  o.data = null; o.byId = null;
  removeLegendBlock(legendEl, `legend-${modo}`);
  setHint('');
}

/* ------------------------------------------------------------ Nivel / ámbito */
function nivelActual(modo) {
  return modo === 'renta' ? 'provincia' : 'municipio';
}
function provinciaAmbito() {
  const s = getState();
  if (s.provincia) return s.provincia;
  if (s.municipio) return String(s.municipio).slice(0, 2);
  return null;
}

async function ensureProvCentroids() {
  if (provCentroids) return provCentroids;
  provCentroids = new Map();
  const geo = await loadGeoJson(MAP_CONFIG.geo.provincias);
  if (geo && geo.features) {
    for (const f of geo.features) {
      const p = f.properties || {};
      const cod = p.cod_ine || p.codigo || p.id;
      if (!cod) continue;
      const c = L.geoJSON(f).getBounds().getCenter();
      provCentroids.set(String(cod).padStart(2, '0'), [c.lat, c.lng]);
    }
  }
  return provCentroids;
}

function centroidFor(nivel, id) {
  return nivel === 'provincia'
    ? (provCentroids ? provCentroids.get(id) : null)
    : getCentroid(id);
}

/* ------------------------------------------------------------ Descarga + pintado */

const _fetchCache = new Map();
const _reqToken = { renta: 0, trabajo: 0, estudios: 0 };

async function refrescarModo(modo) {
  const o = overlays[modo];
  const nivel = nivelActual(modo);
  o.nivel = nivel;
  if (nivel === 'provincia') await ensureProvCentroids();

  const anio = getState().anio;
  const prov = nivel === 'municipio' ? (provinciaAmbito() || '') : '';
  const cacheKey = `${modo}|${anio}|${nivel}|${prov}`;
  const token = ++_reqToken[modo];

  let data = _fetchCache.get(cacheKey);
  if (!data) {
    try {
      const url = new URL(`${API_BASE}/capa/${modo}`, window.location.origin);
      url.searchParams.set('anio', anio);
      url.searchParams.set('nivel', nivel);
      if (prov) url.searchParams.set('provincia', prov);
      const res = await fetch(url.toString(), { headers: { Accept: 'application/json' } });
      if (!res.ok) throw new Error(`capa ${modo} -> ${res.status}`);
      data = await res.json();
      _fetchCache.set(cacheKey, data);
    } catch (err) {
      console.error('[layers] descarga falló:', err.message);
      data = [];
    }
  }

  // Llegó tarde: hay una petición más reciente para este modo -> descartar.
  if (token !== _reqToken[modo]) return;

  o.data = data;
  o.byId = new Map(data.map(d => [d.id, d]));
  if (modo === 'trabajo') pintarTrabajo();
  else pintarCirculos(modo);
}

/* ---- Renta y Estudios: símbolos proporcionales (tamaño) ---- */
function pintarCirculos(modo) {
  const map = getMapInstance();
  const o = overlays[modo];
  const style = LAYER_STYLE[modo];
  if (o.layer) { map.removeLayer(o.layer); o.layer = null; }
  if (!o.data || !o.data.length) { removeLegendBlock(legendEl, `legend-${modo}`); return; }

  const pts = o.data
    .map(d => ({ d, ll: centroidFor(o.nivel, d.id) }))
    .filter(p => p.ll && (o.nivel === 'provincia' || isCodeInScope(p.d.id)));

  const valores = pts.map(p => p.d.valor).filter(v => typeof v === 'number');
  const scale = sizeScale(valores, [CIRCLE_RADIUS.min, CIRCLE_RADIUS.max]);

  const grupo = L.layerGroup([], { pane: `pane-${modo}` });
  for (const { d, ll } of pts) {
    L.circleMarker(ll, {
      pane: `pane-${modo}`,
      renderer: o.renderer,
      radius: scale.radius(d.valor),
      // Anillo: borde de color grueso + relleno muy tenue. Así, si renta y
      // estudios coinciden en el mismo centroide, se ven los dos círculos
      // concéntricos (distinto radio y color) en vez de taparse.
      weight: 2.5,
      color: style.color,
      opacity: 1,
      fillColor: style.color,
      fillOpacity: 0.18,
      interactive: false,   // el hover lo gestiona el polígono base
    }).addTo(grupo);
  }
  grupo.addTo(map);
  o.layer = grupo;

  // Leyenda de TAMAÑO (no de color).
  const fmt = modo === 'renta' ? fmtEuros : fmtPct;
  const nivelTxt = o.nivel === 'provincia' ? 'provincia' : 'municipio';
  let sizes = [];
  if (scale.min != null && scale.max != null) {
    const vals = scale.min === scale.max
      ? [scale.max]
      : [scale.max, (scale.min + scale.max) / 2, scale.min];
    sizes = vals.map(v => ({ r: scale.radius(v), color: style.color, label: fmt(v) }));
  }
  renderLegendBlock(legendEl, `legend-${modo}`, {
    title: `${style.label} · ${nivelTxt}`, sizes,
  });
  setHint('');
}

/* ---- Trabajo: punto por sector dominante (canvas, escala a miles) ---- */
function pintarTrabajo() {
  const map = getMapInstance();
  const o = overlays.trabajo;
  if (o.layer) { map.removeLayer(o.layer); o.layer = null; }
  if (!o.data || !o.data.length) { removeLegendBlock(legendEl, 'legend-trabajo'); return; }

  const pts = o.data
    .map(d => ({ d, ll: centroidFor(o.nivel, d.id) }))
    .filter(p => p.ll && (o.nivel === 'provincia' || isCodeInScope(p.d.id)));

  // A escala municipal el punto es más pequeño (hay miles); a provincia, mayor.
  const r = o.nivel === 'provincia' ? 7 : 4;
  const grupo = L.layerGroup([], { pane: 'pane-trabajo' });
  const presentes = new Set();
  for (const { d, ll } of pts) {
    const key = d.sector in SECTOR_ICONS ? d.sector : 'otros_servicios';
    const ic = SECTOR_ICONS[key];
    presentes.add(key);
    L.circleMarker(ll, {
      pane: 'pane-trabajo',
      renderer: o.renderer,
      radius: r,
      weight: 0.6,
      color: '#ffffff',
      fillColor: ic.color,
      fillOpacity: 0.9,
      interactive: false,   // el hover lo gestiona el polígono base
    }).addTo(grupo);
  }
  grupo.addTo(map);
  o.layer = grupo;

  const nivelTxt = o.nivel === 'provincia' ? 'provincia' : 'municipio';
  // Leyenda: glifo del sector sobre su color (recordatorio visual del color
  // que se ve en el mapa).
  const icons = [...presentes].map(k => ({
    svg: `<svg viewBox="0 0 16 16" width="11" height="11" fill="#fff">${SECTOR_ICONS[k].svg}</svg>`,
    color: SECTOR_ICONS[k].color,
    label: SECTOR_ICONS[k].label,
  }));
  renderLegendBlock(legendEl, 'legend-trabajo', { title: `Sector dominante · ${nivelTxt}`, icons });
  setHint('');
}

/* ------------------------------------------------------------ Tooltip dinámico
   Devuelve las filas de las capas ACTIVAS para un municipio. Si la capa está
   a nivel provincia, busca por el código de provincia del municipio. */
function overlayRows(muniCode) {
  const rows = [];
  for (const modo of ['renta', 'trabajo', 'estudios']) {
    if (!activos.has(modo)) continue;
    const o = overlays[modo];
    if (!o.byId) continue;
    const key = o.nivel === 'provincia' ? String(muniCode).slice(0, 2) : muniCode;
    const rec = o.byId.get(key);
    if (!rec) continue;
    const suf = o.nivel === 'provincia' ? ' (prov.)' : '';
    if (modo === 'trabajo') {
      const ic = SECTOR_ICONS[rec.sector] || SECTOR_ICONS.otros_servicios;
      // rec.valor = empresas DEL SECTOR dominante; rec.total = total del
      // municipio. Mostramos "84 de 227" para que no se confunda el dato del
      // sector con el total.
      const n = formatCompact(rec.valor);
      const tot = rec.total ? ` de ${formatCompact(rec.total)}` : '';
      rows.push({ label: 'Sector dominante' + suf,
                  valueStr: `${ic.label} · ${n}${tot} empresas`, color: ic.color });
    } else {
      const style = LAYER_STYLE[modo];
      const fmt = modo === 'renta' ? fmtEuros : fmtPct;
      rows.push({ label: style.label + suf, valueStr: fmt(rec.valor), color: style.color });
    }
  }
  return rows;
}

/* ------------------------------------------------------------ Formato */
const nfEur = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 0 });
function fmtEuros(v) { return (v == null) ? '—' : nfEur.format(v) + ' €'; }
function fmtPct(v)   { return (v == null) ? '—' : v.toFixed(1) + ' %'; }