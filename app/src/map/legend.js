/* Leyenda discreta del mapa (cuantiles). */

import { escapeHtml } from '../utils/html.js';

export function renderLegend(container, { title, ranges }) {
  if (!container) return;

  if (!ranges || ranges.length === 0) {
    container.innerHTML = '';
    container.setAttribute('aria-hidden', 'true');
    return;
  }

  container.setAttribute('aria-hidden', 'false');
  container.innerHTML = `
    <div class="map-legend__title">${escapeHtml(title)}</div>
    ${ranges.map(r => `
      <div class="map-legend__row">
        <span class="map-legend__swatch" style="background:${escapeHtml(r.color)}"></span>
        <span>${escapeHtml(r.label)}</span>
      </div>
    `).join('')}
  `;
}
