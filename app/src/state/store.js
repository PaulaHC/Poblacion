const state = {
  comunidad: null,   
  provincia: null,  
  municipio: null,   
  sexo:      'total',
  anio:      2025,
};

const listeners = new Set();

export function getState() {
  return { ...state };
}


export function setState(patch) {
  const changed = [];
  for (const k of Object.keys(patch)) {
    if (state[k] !== patch[k]) {
      state[k] = patch[k];
      changed.push(k);
    }
  }
  if (changed.length === 0) return changed;
  const snapshot = getState();
  listeners.forEach(fn => {
    try { fn(snapshot, changed); }
    catch (err) { console.error('[store] listener error:', err); }
  });
  return changed;
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

if (typeof window !== 'undefined') {
  window.__store = { getState, setState, subscribe };
}
