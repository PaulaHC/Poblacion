const HTML_ENTITIES = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};

export function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => HTML_ENTITIES[c]);
}

export function escapeAttr(s) {
  return String(s ?? '').replace(/"/g, '&quot;');
}
