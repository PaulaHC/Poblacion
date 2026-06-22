import { API_BASE } from '../config.js';

async function getJson(path, params = {}) {
  const url = new URL(API_BASE + path, window.location.origin);
  for (const [k, v] of Object.entries(params)) {
    if (v != null && v !== '') url.searchParams.set(k, v);
  }
  const res = await fetch(url.toString(), { headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error(`API ${path} -> ${res.status}`);
  return res.json();
}

export function fetchComunidades() {
  return getJson('/comunidades').catch(err => {
    console.error('[influx] fetchComunidades falló:', err.message);
    return [];
  });
}


export function fetchProvincias(comunidad) {
  return getJson('/provincias', { comunidad }).catch(err => {
    console.error('[influx] fetchProvincias falló:', err.message);
    return [];
  });
}
export function fetchMunicipios(opts = {}) {
  if (typeof opts === 'string') opts = { provincia: opts };
  const { provincia, comunidad, q, limit } = opts;
  return getJson('/municipios', { provincia, comunidad, q, limit }).catch(err => {
    console.error('[influx] fetchMunicipios falló:', err.message);
    return [];
  });
}

export function fetchValoresMapa({ anio, sexo, comunidad, provincia, municipio } = {}) {
  return getJson('/mapa', { anio, sexo, comunidad, provincia, municipio })
    .then(rows => {
      const map = {};
      for (const r of rows) map[r.id] = r.valor;
      return map;
    })
    .catch(err => {
      console.error('[influx] fetchValoresMapa falló:', err.message);
      return {};
    });
}