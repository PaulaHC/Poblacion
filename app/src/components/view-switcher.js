const VIEWS = ['mapa', 'graficos', 'estadisticas'];

export function mountViewSwitcher({ getMap } = {}) {
  const buttons = document.querySelectorAll('.view-btn');
  if (!buttons.length) return;

  function setView(view) {
    if (!VIEWS.includes(view)) return;

    // Botones
    buttons.forEach((btn) => {
      const active = btn.dataset.view === view;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-selected', active ? 'true' : 'false');
    });

    // Paneles
    VIEWS.forEach((v) => {
      const panel = document.getElementById(`view-${v}`);
      if (!panel) return;
      const active = v === view;
      panel.classList.toggle('is-active', active);
      if (active) panel.removeAttribute('hidden');
      else panel.setAttribute('hidden', '');
    });

    if (view === 'mapa' && typeof getMap === 'function') {
      const map = getMap();
      if (map && typeof map.invalidateSize === 'function') {
        setTimeout(() => map.invalidateSize(), 0);
      }
    }

    document.dispatchEvent(new CustomEvent('poview:viewchange', { detail: { view } }));
  }

  buttons.forEach((btn) => {
    btn.addEventListener('click', () => setView(btn.dataset.view));
  });

  return { setView };
}