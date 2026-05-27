import { getState, setState, subscribe } from '../state/store.js';
import { debounce } from '../utils/debounce.js';
import { escapeHtml, escapeAttr } from '../utils/html.js';
import { fetchComunidades, fetchProvincias, fetchMunicipios } from '../api/influx.js';

export async function mountFilters() {
  const elComunidad = document.getElementById('f-comunidad');
  const elProvincia = document.getElementById('f-provincia');
  const elMunicipio = document.getElementById('f-municipio');
  const elAnio      = document.getElementById('f-anio');
  const elAnioOut   = document.getElementById('f-anio-out');
  const sexoInputs  = document.querySelectorAll('input[name="sexo"]');

  // Mientras carga, los selects deben mostrarse como bloqueados pero con
  // un texto significativo, no como un "Todas" engañoso.
  setLoading(elComunidad, true,  'Cargando…');
  setLoading(elProvincia, true,  'Cargando…');
  setLoading(elMunicipio, true,  'Selecciona provincia');

  /* ---- Carga inicial ---- */
  try {
    const [comunidades, provincias] = await Promise.all([
      fetchComunidades(),
      fetchProvincias(),
    ]);
    populateSelect(elComunidad, comunidades, 'Todas');
    elComunidad.disabled = comunidades.length === 0;

    populateSelect(elProvincia, provincias, 'Todas');
    elProvincia.disabled = provincias.length === 0;
  } catch (err) {
    console.error('[filters] carga inicial falló:', err);
    populateSelect(elComunidad, [], 'Sin datos');
    populateSelect(elProvincia, [], 'Sin datos');
  } finally {
    // Municipio sigue bloqueado hasta que se elija provincia
    populateSelect(elMunicipio, [], 'Selecciona una provincia');
    elMunicipio.disabled = true;
  }

  /* ---- UI -> Store ---- */
  elComunidad.addEventListener('change', async (e) => {
    const value = e.target.value || null;
    setState({ comunidad: value, provincia: null, municipio: null });

    // Mientras llega la lista, bloqueamos provincia con un texto claro
    setLoading(elProvincia, true, 'Cargando…');
    populateSelect(elMunicipio, [], 'Selecciona una provincia');
    elMunicipio.disabled = true;

    const provs = await fetchProvincias(value);
    populateSelect(elProvincia, provs, 'Todas');
    elProvincia.disabled = provs.length === 0;
  });

  elProvincia.addEventListener('change', async (e) => {
    const value = e.target.value || null;
    setState({ provincia: value, municipio: null });

    if (!value) {
      populateSelect(elMunicipio, [], 'Selecciona una provincia');
      elMunicipio.disabled = true;
      return;
    }

    setLoading(elMunicipio, true, 'Cargando…');
    const munis = await fetchMunicipios(value);
    populateSelect(elMunicipio, munis, 'Todos');
    elMunicipio.disabled = munis.length === 0;
  });

  elMunicipio.addEventListener('change', (e) => {
    setState({ municipio: e.target.value || null });
  });

  // Slider de año: feedback inmediato en la etiqueta, pero debounce
  // antes de tocar el store (que dispara la consulta a Influx).
  const debouncedAnio = debounce((v) => setState({ anio: Number(v) }), 300);
  elAnio.addEventListener('input', (e) => {
    const v = e.target.value;
    elAnioOut.textContent = v;
    debouncedAnio(v);
  });

  sexoInputs.forEach(inp => {
    inp.addEventListener('change', (e) => {
      if (e.target.checked) setState({ sexo: e.target.value });
    });
  });

  /* ---- Store -> UI (cuando otro componente —p.ej. el mapa al hacer
                       click— empuja un cambio de selección) ---- */
  subscribe(syncUiFromState);
  syncUiFromState(getState());

  async function syncUiFromState(s) {
    if (elComunidad.value !== (s.comunidad || '')) {
      elComunidad.value = s.comunidad || '';
    }
    if (elProvincia.value !== (s.provincia || '')) {
      if (s.provincia && !hasOption(elProvincia, s.provincia)) {
        const provs = await fetchProvincias(s.comunidad);
        populateSelect(elProvincia, provs, 'Todas');
        elProvincia.disabled = provs.length === 0;
      }
      elProvincia.value = s.provincia || '';
    }
    if (elMunicipio.value !== (s.municipio || '')) {
      if (s.provincia && s.municipio && !hasOption(elMunicipio, s.municipio)) {
        const munis = await fetchMunicipios(s.provincia);
        populateSelect(elMunicipio, munis, 'Todos');
        elMunicipio.disabled = munis.length === 0;
      }
      elMunicipio.value = s.municipio || '';
    }
    if (elAnio.value !== String(s.anio)) {
      elAnio.value = s.anio;
      elAnioOut.textContent = s.anio;
    }
    sexoInputs.forEach(inp => { inp.checked = (inp.value === s.sexo); });
  }
}

function populateSelect(select, items, emptyLabel) {
  const current = select.value;
  select.innerHTML = `<option value="">${escapeHtml(emptyLabel)}</option>` +
    items.map(it =>
      `<option value="${escapeAttr(it.id)}">${escapeHtml(it.nombre)}</option>`
    ).join('');
  if (current && [...select.options].some(o => o.value === current)) {
    select.value = current;
  }
}

function hasOption(select, value) {
  if (!value) return true;
  return [...select.options].some(o => o.value === value);
}

function setLoading(select, on, label) {
  select.disabled = on;
  if (on) {
    select.innerHTML = `<option value="">${escapeHtml(label)}</option>`;
  }
}