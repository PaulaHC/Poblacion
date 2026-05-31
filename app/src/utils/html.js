const HTML_ENTITIES = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};

/** Escapa una cadena para insertarla como texto u atributo HTML. */
export function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => HTML_ENTITIES[c]);
}

/** Atajo: solo escapa lo mínimo para un atributo entre comillas dobles. */
export function escapeAttr(s) {
  return String(s ?? '').replace(/"/g, '&quot;');
}
