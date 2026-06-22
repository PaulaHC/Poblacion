import 'leaflet/dist/leaflet.css';
import * as L      from 'leaflet';
import * as echarts from 'echarts';

// El resto del código sigue usando L / echarts como globales (mapa, charts).
// Mantenemos los globales para no tocar map.js / charts.js.
window.L       = L;
window.echarts = echarts;

import './styles.css';
import { mountFilters }      from './components/filters.js';
import { mountChat }         from './components/chat.js';
import { mountViewSwitcher } from './components/view-switcher.js';
import { mountCharts }       from './components/charts.js';
import { mountStats }        from './components/stats.js';
import { createMap }         from './map/map.js';
import { mountLayers }       from './map/layers.js';

function boot() {
  safeMount('filters',  () => mountFilters().catch(e => console.error('[filters]', e)));

  let map = null;
  safeMount('map',      () => { map = createMap(document.getElementById('map')); });
  safeMount('layers',   () => mountLayers().catch(e => console.error('[layers]', e)));

  safeMount('chat',     () => mountChat());
  safeMount('charts',   () => mountCharts());
  safeMount('stats',    () => mountStats());
  safeMount('switcher', () => mountViewSwitcher({ getMap: () => map }));
}

function safeMount(name, fn) {
  try { fn(); }
  catch (err) { console.error(`[boot] ${name} falló:`, err); }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}