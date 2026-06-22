const cache = new Map();

async function fetchJsonOnce(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`GeoJSON ${url} -> ${r.status}`);

  const ctype = (r.headers.get('content-type') || '').toLowerCase();
  if (ctype.includes('text/html')) {
    throw new Error(`GeoJSON ${url} devolvió HTML (¿servidor no listo?)`);
  }
  return r.json();
}

export function loadGeoJson(url) {
  if (cache.has(url)) return cache.get(url);

  const p = (async () => {
    try {
      return await fetchJsonOnce(url);
    } catch (err1) {
      console.warn('[geo] primer intento fallido, reintentando…', url, err1.message);

      await new Promise(res => setTimeout(res, 400));
      try {
        return await fetchJsonOnce(url);
      } catch (err2) {
        console.error('[geo] no se pudo cargar', url, err2.message);

        cache.delete(url);
        return null;
      }
    }
  })();

  cache.set(url, p);
  return p;
}