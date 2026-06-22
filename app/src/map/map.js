import { MAP_CONFIG, RAMP_POBLACION, PANE_ZINDEX } from '../config.js';
import { loadGeoJson } from '../api/geo.js';
import { fetchValoresMapa, fetchProvincias } from '../api/influx.js';
import { getState, setState, subscribe } from '../state/store.js';
import { quantileScale, legendRanges } from '../utils/color-scale.js';
import { formatCompact } from '../utils/format.js';
import { escapeHtml } from '../utils/html.js';
import { renderLegendBlock, removeLegendBlock } from './legend.js';

const SEXO_LABELS = { total: 'Total', hombres: 'Hombres', mujeres: 'Mujeres' };

const STYLE = {
  filled:     { weight: 0.5,  color: '#ffffff', fillOpacity: 0.85 },
  noData:     { weight: 0.3,  color: '#9ca3af', fillColor: '#ffffff', fillOpacity: 0.0 },
  outOfScope: { weight: 0.15, color: '#cbd5e1', fillColor: '#94a3b8', fillOpacity: 0.05 },
  focused:    { weight: 2.2,  color: '#0F172A', fillOpacity: 0.95 },
  hover:      { weight: 1.5,  color: '#0F172A' },
  hidden:     { weight: 0,    fillOpacity: 0.0, opacity: 0.0 },
};

const state = {
  map: null,
  layer: null,
  geo: null,
  byCode: new Map(),
  centroids: new Map(),
  values: {},
  scale: null,
  provinciasPorCcaa: new Map(),
  baseVisible: true,
};

let lastScopeKey = null;
let lastFocus    = null;
let bootstrapPromise = null;
let tooltipProvider = null;

/* ============================================================
   API pública
   ============================================================ */
export function createMap(container) {
  state.map = L.map(container, {
    center: MAP_CONFIG.center,
    zoom: MAP_CONFIG.zoom,
    minZoom: MAP_CONFIG.minZoom,
    maxZoom: MAP_CONFIG.maxZoom,
    zoomControl: true,
    preferCanvas: true,
  });

  for (const [name, z] of Object.entries(PANE_ZINDEX)) {
    state.map.createPane(`pane-${name}`);
    const pane = state.map.getPane(`pane-${name}`);
    pane.style.zIndex = String(z);
    if (name !== 'poblacion') pane.style.pointerEvents = 'none';
  }

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: MAP_CONFIG.maxZoom,
  }).addTo(state.map);

  bootstrapPromise = bootstrap().catch(err => console.error('[map] bootstrap:', err));
  subscribe(onStateChange);

  return state.map;
}

/* ============================================================
   Bootstrap
   ============================================================ */
async function bootstrap() {
  const geo = await loadGeoJson(MAP_CONFIG.geo.municipiosLow);
  if (!geo || !geo.features) {
    console.error('[map] no se pudo cargar geometría de municipios');
    return;
  }
  state.geo = geo;

  state.layer = L.geoJSON(geo, {
    pane: 'pane-poblacion',
    style: STYLE.noData,
    onEachFeature: (feature, layer) => {
      const code = getMuniCode(feature);
      if (code) state.byCode.set(code, { feature, layer });
      bindInteractions(feature, layer);
    },
  });
  state.layer.addTo(state.map);

  await refresh();
}

/* ============================================================
   Reacción a cambios de estado
   ============================================================ */
async function onStateChange(s) {
  if (!state.geo) {
    if (bootstrapPromise) await bootstrapPromise;
    if (!state.geo) return;
  }

  await refresh();

  const scopeKey = currentScopeKey(s);
  const focus    = s.municipio || null;

  if (scopeKey !== lastScopeKey) {
    fitToScope(s);
    lastScopeKey = scopeKey;
  }
  if (focus !== lastFocus) {
    if (focus) fitToFeatureByCode(focus);
    lastFocus = focus;
  }
}

/* ============================================================
   refresh(): consulta valores y repinta toda la capa
   ============================================================ */
async function refresh() {
  if (!state.layer) return;
  const s = getState();

  const values = await fetchValoresMapa({
    anio:      s.anio,
    sexo:      s.sexo,
    comunidad: s.comunidad,
    provincia: s.provincia,
  });
  state.values = values || {};

  const numbers = Object.values(state.values).filter(v => typeof v === 'number');
  state.scale = quantileScale(numbers, RAMP_POBLACION);

  applyStyles();
  updateLegend();
  updateMeta();
}

/* ============================================================
   applyStyles()
   ============================================================ */
function applyStyles() {
  if (!state.byCode.size) return;
  const s = getState();

  if (!state.baseVisible) {
    state.byCode.forEach(({ layer }) => layer.setStyle(STYLE.hidden));
    return;
  }

  const focusedCode = s.municipio || null;
  const hasScope = Boolean(s.comunidad || s.provincia);
  const color = (v) => state.scale ? state.scale.color(v) : '#cbd5e1';

  state.byCode.forEach(({ feature, layer }, code) => {
    const inScope = isInScope(feature, s);
    const value   = state.values[code];

    if (focusedCode && code === focusedCode) {
      const c = (typeof value === 'number') ? color(value) : '#1E3A8A';
      layer.setStyle({ ...STYLE.filled, ...STYLE.focused, fillColor: c });
      layer.bringToFront();
      return;
    }

    if (hasScope && !inScope) {
      layer.setStyle(STYLE.outOfScope);
      return;
    }

    if (focusedCode && code !== focusedCode) {
      layer.setStyle(STYLE.noData);
      return;
    }

    if (typeof value === 'number') {
      layer.setStyle({ ...STYLE.filled, fillColor: color(value) });
    } else {
      layer.setStyle(STYLE.noData);
    }
  });
}

/* ============================================================
   Interacciones
   ============================================================ */
function bindInteractions(feature, layer) {
  layer.bindTooltip(() => tooltipHtml(feature), {
    sticky: true,
    direction: 'top',
    className: 'map-tooltip',
    opacity: 0.95,
  });

  layer.on('mouseover', (e) => {
    const s = getState();
    const code = getMuniCode(feature);
    if (s.municipio && code !== s.municipio) return;
    if ((s.comunidad || s.provincia) && !isInScope(feature, s)) return;
    e.target.setStyle(STYLE.hover);
    e.target.bringToFront();
  });

  layer.on('mouseout', () => applyStyles());

  layer.on('click', () => {
    const code = getMuniCode(feature);
    if (!code) return;
    const s = getState();
    if ((s.comunidad || s.provincia) && !isInScope(feature, s)) return;
    setState({ municipio: code });
  });
}

/* ============================================================
   Tooltip dinámico: muestra solo los modos activos en ese momento
   ============================================================ */
function tooltipHtml(feature) {
  const code = getMuniCode(feature);
  const name = getMuniName(feature);
  const rows = [];

  if (state.baseVisible) {
    const v = state.values[code];
    const sexo = SEXO_LABELS[getState().sexo] || 'Total';
    const val = (typeof v === 'number')
      ? `<strong>${formatCompact(v)}</strong> hab.`
      : '<em style="opacity:.7">sin dato</em>';
    rows.push(`<span class="tt-dot" style="background:#1E3A8A"></span>Población (${escapeHtml(sexo)}): ${val}`);
  }

  if (tooltipProvider) {
    for (const r of tooltipProvider(code)) {
      rows.push(`<span class="tt-dot" style="background:${escapeHtml(r.color)}"></span>` +
                `${escapeHtml(r.label)}: <strong>${escapeHtml(r.valueStr)}</strong>`);
    }
  }

  if (!rows.length) rows.push('<em style="opacity:.7">ninguna capa activa</em>');

  return `<div style="line-height:1.55">
    <div style="margin-bottom:2px"><strong>${escapeHtml(name)}</strong></div>
    ${rows.map(r => `<div>${r}</div>`).join('')}
  </div>`;
}

/* ============================================================
   Ámbito y enfoque
   ============================================================ */
function currentScopeKey(s) {
  if (s.provincia) return `p:${s.provincia}`;
  if (s.comunidad) return `c:${s.comunidad}`;
  return 'all';
}

function isInScope(feature, s) {
  if (s.provincia) {
    const provCode = String(getMuniCode(feature) || '').slice(0, 2);
    return provCode === s.provincia;
  }
  if (s.comunidad) {
    const provsCcaa = state.provinciasPorCcaa.get(s.comunidad);
    if (!provsCcaa) return true;
    const provCode = String(getMuniCode(feature) || '').slice(0, 2);
    return provsCcaa.has(provCode);
  }
  return true;
}

async function ensureProvinciasParaCcaa(ccaa) {
  if (!ccaa || state.provinciasPorCcaa.has(ccaa)) return;
  try {
    const list = await fetchProvincias(ccaa);
    state.provinciasPorCcaa.set(ccaa, new Set(list.map(p => p.id)));
  } catch (err) {
    console.warn('[map] no se pudieron precargar provincias de', ccaa, err);
  }
}

/* ============================================================
   Encuadres (con guard para state.geo nulo)
   ============================================================ */
function fitToScope(s) {
  if (!state.geo || !state.geo.features) return;   // guard
  if (s.municipio) return;

  if (s.provincia) {
    const features = state.geo.features.filter(f => {
      const p = String(getMuniCode(f) || '').slice(0, 2);
      return p === s.provincia;
    });
    fitToFeatures(features, { padding: [40, 40], maxZoom: 11 });
    return;
  }

  if (s.comunidad) {
    ensureProvinciasParaCcaa(s.comunidad).then(() => {
      if (!state.geo || !state.geo.features) return;
      const provs = state.provinciasPorCcaa.get(s.comunidad) || new Set();
      const features = state.geo.features.filter(f => {
        const p = String(getMuniCode(f) || '').slice(0, 2);
        return provs.has(p);
      });
      fitToFeatures(features, { padding: [40, 40], maxZoom: 9 });
      applyStyles();
    });
    return;
  }

  state.map.flyTo(MAP_CONFIG.center, MAP_CONFIG.zoom, { duration: 0.6 });
}

function fitToFeatureByCode(code) {
  const entry = state.byCode.get(code);
  if (!entry) return;
  const bounds = entry.layer.getBounds();
  if (bounds.isValid()) {
    state.map.fitBounds(bounds, { padding: [60, 60], maxZoom: 13 });
  }
}

function fitToFeatures(features, opts) {
  if (!features || features.length === 0) return;
  const group = L.featureGroup(features.map(f => L.geoJSON(f)));
  const bounds = group.getBounds();
  if (bounds.isValid()) state.map.fitBounds(bounds, opts);
}

/* ============================================================
   Leyenda y meta
   ============================================================ */
function updateLegend() {
  const el = document.getElementById('map-legend');
  if (!el) return;
  if (!state.baseVisible) {
    removeLegendBlock(el, 'legend-poblacion');
    return;
  }
  const ranges = state.scale ? legendRanges(state.scale, formatCompact) : [];
  renderLegendBlock(el, 'legend-poblacion', {
    title: `Población · ${SEXO_LABELS[getState().sexo] || 'Total'}`,
    ranges,
  });
}

function updateMeta() {
  const s = getState();
  const meta = document.getElementById('map-meta');
  if (meta) {
    meta.textContent = `Población · ${SEXO_LABELS[s.sexo] || 'Total'} · ${s.anio}`;
  }
  const title = document.getElementById('map-title');
  if (title) {
    let scope = 'España';
    if (s.provincia) scope = `Provincia ${s.provincia}`;
    if (s.comunidad && !s.provincia) scope = s.comunidad;
    if (s.municipio) {
      const f = state.byCode.get(s.municipio)?.feature;
      if (f) scope = getMuniName(f);
    }
    title.textContent = `Mapa coroplético · ${scope}`;
  }
}

/* ============================================================
   Helpers
   ============================================================ */
function getMuniCode(f) {
  const p = f.properties || {};
  return p.cod_ine || p.CODIGOINE || p.NATCODE || p.codigo || p.id || null;
}
function getMuniName(f) {
  const p = f.properties || {};
  return p.nombre || p.NAMEUNIT || p.name || 'Sin nombre';
}

export function whenMapReady() {
  return bootstrapPromise || Promise.resolve();
}

export function getMapInstance() {
  return state.map;
}

export function getCentroid(code) {
  if (state.centroids.has(code)) return state.centroids.get(code);
  const entry = state.byCode.get(code);
  if (!entry) return null;
  const c = entry.layer.getBounds().getCenter();
  const latlng = [c.lat, c.lng];
  state.centroids.set(code, latlng);
  return latlng;
}

export function isCodeInScope(code) {
  const entry = state.byCode.get(code);
  if (!entry) return false;
  return isInScope(entry.feature, getState());
}

export function setBaseVisible(visible) {
  state.baseVisible = Boolean(visible);
  applyStyles();
  updateLegend();
}


export function setTooltipProvider(fn) {
  tooltipProvider = fn;
}

export function getMuniNameByCode(code) {
  const entry = state.byCode.get(code);
  return entry ? getMuniName(entry.feature) : code;
}