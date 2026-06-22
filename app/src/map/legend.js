import { escapeHtml } from '../utils/html.js';

function ensureBlock(parent, id) {
  let el = parent.querySelector('#' + id);
  if (!el) {
    el = document.createElement('div');
    el.id = id;
    el.className = 'map-legend__block';
    parent.appendChild(el);
  }
  return el;
}

function syncHidden(parent) {
  parent.setAttribute('aria-hidden', parent.children.length ? 'false' : 'true');
}

function swatchRow(color, label) {
  return `<div class="map-legend__row">
    <span class="map-legend__swatch" style="background:${escapeHtml(color)}"></span>
    <span>${escapeHtml(label)}</span>
  </div>`;
}

function iconRow(svg, color, label) {
  return `<div class="map-legend__row">
    <span class="map-legend__icon" style="background:${escapeHtml(color)}">${svg}</span>
    <span>${escapeHtml(label)}</span>
  </div>`;
}

function sizeRow(r, color, label) {
  const d = Math.round(r * 2);
  return `<div class="map-legend__row">
    <span class="map-legend__sizewrap">
      <span class="map-legend__circle" style="width:${d}px;height:${d}px;background:${escapeHtml(color)}"></span>
    </span>
    <span>${escapeHtml(label)}</span>
  </div>`;
}


export function renderLegendBlock(parent, id, { title, ranges = [], icons = [], sizes = [] } = {}) {
  if (!parent) return;
  if (ranges.length === 0 && icons.length === 0 && sizes.length === 0) {
    removeLegendBlock(parent, id);
    return;
  }
  const el = ensureBlock(parent, id);
  const rows = [
    ...ranges.map(r => swatchRow(r.color, r.label)),
    ...sizes.map(s => sizeRow(s.r, s.color, s.label)),
    ...icons.map(i => iconRow(i.svg, i.color, i.label)),
  ].join('');
  el.innerHTML = `<div class="map-legend__title">${escapeHtml(title)}</div>${rows}`;
  syncHidden(parent);
}

export function removeLegendBlock(parent, id) {
  if (!parent) return;
  const ex = parent.querySelector('#' + id);
  if (ex) ex.remove();
  syncHidden(parent);
}