import { getState, setState, subscribe } from '../state/store.js';
import { debounce } from '../utils/debounce.js';
import { escapeHtml, escapeAttr } from '../utils/html.js';
import { fetchComunidades, fetchProvincias, fetchMunicipios } from '../api/influx.js';

/* -----------------------------------------------------------
 *  Municipio: combobox con autocompletado
 * -----------------------------------------------------------
 *  El HTML original contiene <select id="f-municipio">. Lo dejamos
 *  oculto en el DOM (sigue siendo la "fuente de verdad" para el
 *  estado seleccionado) y, justo a su lado, montamos un input + datalist.
 *  Así obtenemos:
 *    - búsqueda por texto (clave cuando hay 8 000+ municipios),
 *    - compatibilidad con el resto del código que ya consulta
 *      f-municipio.value vía syncUiFromState.
 * --------------------------------------------------------- */

// caché en memoria para no machacar el endpoint en cada tecla
const muniCache = new Map(); // key = JSON({prov, ccaa, q}) → array
async function fetchMunicipiosCached(opts) {
  const key = JSON.stringify({
    p: opts.provincia || '',
    c: opts.comunidad || '',
    q: (opts.q || '').toLowerCase(),
  });
  if (muniCache.has(key)) return muniCache.get(key);
  const data = await fetchMunicipios(opts);
  muniCache.set(key, data);
  return data;
}

// Catálogo "vivo" del último listado pintado en el datalist; lo usamos
// para resolver, al elegir, el cod_provincia y la comunidad del municipio.
let muniCatalog = []; // [{ id, nombre, cod_provincia, provincia, comunidad }]

export async function mountFilters() {
  const elComunidad = document.getElementById('f-comunidad');
  const elProvincia = document.getElementById('f-provincia');
  const elMunicipio = document.getElementById('f-municipio');
  const elAnio      = document.getElementById('f-anio');
  const elAnioOut   = document.getElementById('f-anio-out');
  const sexoInputs  = document.querySelectorAll('input[name="sexo"]');

  // --- Montaje del combobox de municipio sobre el <select> ---
  // Ocultamos el select (sin quitarlo: el resto del código lee su value)
  elMunicipio.style.display = 'none';

  // El <select> está dentro de un <label class="field">. Si dejamos el combo
  // dentro de ese label, los clicks en la lista hacen que el label intente
  // enfocar el control (el select), cerrando el desplegable. Lo extraemos
  // a un contenedor neutral, justo detrás del label.
  const fieldLabel = elMunicipio.closest('label');
  const muniBox = document.createElement('div');
  muniBox.className = 'muni-combo';
  muniBox.innerHTML = `
    <input
      type="text"
      id="f-municipio-input"
      class="field__control"
      autocomplete="off"
      spellcheck="false"
      placeholder="Todos"
    >
    <button
      type="button"
      class="muni-combo__clear"
      id="f-municipio-clear"
      aria-label="Borrar municipio"
      hidden
    >×</button>
    <div class="muni-combo__list" id="f-municipio-list" hidden role="listbox"></div>
    <div class="muni-combo__hint" id="f-municipio-hint"></div>
  `;
  if (fieldLabel && fieldLabel.parentNode) {
    fieldLabel.parentNode.insertBefore(muniBox, fieldLabel.nextSibling);
  } else {
    elMunicipio.parentNode.appendChild(muniBox);
  }

  const muniInput = muniBox.querySelector('#f-municipio-input');
  const muniList  = muniBox.querySelector('#f-municipio-list');
  const muniHint  = muniBox.querySelector('#f-municipio-hint');
  const muniClear = muniBox.querySelector('#f-municipio-clear');

  // Mientras carga, los selects deben mostrarse como bloqueados
  setLoading(elComunidad, true,  'Cargando…');
  setLoading(elProvincia, true,  'Cargando…');
  muniInput.disabled = true;
  muniInput.placeholder = 'Cargando…';

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
    muniInput.disabled = false;
    muniInput.placeholder = 'Buscar municipio…';
    muniHint.textContent = 'Escribe al menos 2 letras o elige una provincia';
  }

  /* ---- UI -> Store ---- */
  elComunidad.addEventListener('change', async (e) => {
    const value = e.target.value || null;
    // Limpiar provincia y municipio: el cambio de ámbito invalida el contexto.
    setState({ comunidad: value, provincia: null, municipio: null });
    clearMuniInput();
    muniCatalog = [];

    setLoading(elProvincia, true, 'Cargando…');
    const provs = await fetchProvincias(value);
    populateSelect(elProvincia, provs, 'Todas');
    elProvincia.disabled = provs.length === 0;

    // Si hay comunidad seleccionada, precargamos la lista de municipios
    // (puede ser grande, pero el combobox la filtra por texto).
    refreshMuniHint();
  });

  elProvincia.addEventListener('change', async (e) => {
    const value = e.target.value || null;
    setState({ provincia: value, municipio: null });
    clearMuniInput();
    muniCatalog = [];
    refreshMuniHint();
  });

  /* ---- Combobox de municipio ---- */
  // Buscar mientras se escribe (debounced)
  const onType = debounce(async () => {
    const q = muniInput.value.trim();
    const s = getState();
    // Reglas:
    //   - si hay provincia, listamos todos los de la provincia (sin q).
    //   - si no, requerimos al menos 2 letras para no descargar todo.
    if (!s.provincia && q.length < 2) {
      hideList();
      refreshMuniHint();
      return;
    }
    const opts = { provincia: s.provincia, comunidad: s.comunidad };
    if (!s.provincia) opts.q = q;
    const items = await fetchMunicipiosCached(opts);
    muniCatalog = items;
    // En modo provincia filtramos en cliente por la cadena tecleada
    const visible = s.provincia && q
      ? items.filter(it => normalize(it.nombre).includes(normalize(q)))
      : items;
    renderList(visible.slice(0, 100), q);
    muniHint.textContent = items.length > 100
      ? `${items.length} resultados · mostrando 100`
      : `${visible.length} resultados`;
  }, 180);

  muniInput.addEventListener('input', () => {
    muniClear.hidden = muniInput.value.length === 0;
    onType();
  });
  muniInput.addEventListener('focus', () => {
    if (muniInput.value || getState().provincia) onType();
  });
  muniInput.addEventListener('blur', () => {
    // pequeño delay para permitir click sobre la lista
    setTimeout(hideList, 150);
  });
  muniInput.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      hideList();
      muniInput.blur();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const first = muniList.querySelector('.muni-combo__item');
      if (first) first.click();
    }
  });

  muniClear.addEventListener('click', () => {
    clearMuniInput();
    setState({ municipio: null });
    muniInput.focus();
  });

  /* ---- Año y sexo ---- */
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

  /* ---- Store -> UI (sync) ---- */
  subscribe(syncUiFromState);
  syncUiFromState(getState());

  /* ---- helpers locales ---- */
  function renderList(items, qHighlight) {
    if (!items.length) {
      muniList.innerHTML = `<div class="muni-combo__empty">Sin coincidencias</div>`;
    } else {
      muniList.innerHTML = items.map(it => {
        const sub = [it.provincia, it.comunidad].filter(Boolean).join(' · ');
        return `
          <div class="muni-combo__item" role="option"
               data-cod="${escapeAttr(it.id)}"
               data-prov="${escapeAttr(it.cod_provincia || '')}"
               data-ccaa="${escapeAttr(it.comunidad || '')}">
            <span class="muni-combo__name">${highlight(it.nombre, qHighlight)}</span>
            ${sub ? `<span class="muni-combo__sub">${escapeHtml(sub)}</span>` : ''}
          </div>
        `;
      }).join('');
    }
    muniList.hidden = false;
    // delegación de click
    muniList.querySelectorAll('.muni-combo__item').forEach(el => {
      el.addEventListener('mousedown', (ev) => {
        // mousedown en vez de click para anticipar al blur del input
        ev.preventDefault();
        const cod  = el.dataset.cod;
        const prov = el.dataset.prov || null;
        const ccaa = el.dataset.ccaa || null;
        const nom  = el.querySelector('.muni-combo__name').textContent;

        muniInput.value = nom;
        muniClear.hidden = false;
        hideList();

        // Si el usuario buscó "suelto" (sin provincia previa), autocompletamos.
        const patch = { municipio: cod };
        const s = getState();
        if (prov && !s.provincia) patch.provincia = prov;
        if (ccaa && !s.comunidad) patch.comunidad = ccaa;
        setState(patch);
      });
    });
  }

  function hideList() { muniList.hidden = true; }

  function clearMuniInput() {
    muniInput.value = '';
    muniClear.hidden = true;
    hideList();
  }

  function refreshMuniHint() {
    const s = getState();
    if (s.provincia)      muniHint.textContent = 'Filtra dentro de la provincia';
    else if (s.comunidad) muniHint.textContent = 'Escribe para buscar en la comunidad';
    else                  muniHint.textContent = 'Escribe al menos 2 letras (busca en toda España)';
  }

  async function syncUiFromState(s) {
    if (elComunidad.value !== (s.comunidad || '')) {
      // Si el cambio viene del store y la opción no estaba aún cargada
      // (caso de seleccionar municipio "suelto"), recargamos provincias.
      if (s.comunidad && !hasOption(elComunidad, s.comunidad)) {
        const ccaas = await fetchComunidades();
        populateSelect(elComunidad, ccaas, 'Todas');
        elComunidad.disabled = ccaas.length === 0;
      }
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

    // Mantener el <select> oculto sincronizado para no romper el resto del código
    if (elMunicipio.value !== (s.municipio || '')) {
      // garantizar que exista la option
      if (s.municipio && !hasOption(elMunicipio, s.municipio)) {
        const opt = document.createElement('option');
        opt.value = s.municipio;
        opt.textContent = muniInput.value || s.municipio;
        elMunicipio.appendChild(opt);
      }
      elMunicipio.value = s.municipio || '';
    }
    if (!s.municipio && muniInput.value) {
      clearMuniInput();
    }

    if (elAnio.value !== String(s.anio)) {
      elAnio.value = s.anio;
      elAnioOut.textContent = s.anio;
    }
    sexoInputs.forEach(inp => { inp.checked = (inp.value === s.sexo); });
    refreshMuniHint();
  }
}

/* -----------------------------------------------------------
 *  Utilidades
 * --------------------------------------------------------- */
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

function normalize(s) {
  return (s || '').toLowerCase()
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '');
}

function highlight(name, q) {
  if (!q) return escapeHtml(name);
  const i = normalize(name).indexOf(normalize(q));
  if (i < 0) return escapeHtml(name);
  const a = name.slice(0, i);
  const b = name.slice(i, i + q.length);
  const c = name.slice(i + q.length);
  return `${escapeHtml(a)}<mark>${escapeHtml(b)}</mark>${escapeHtml(c)}`;
}