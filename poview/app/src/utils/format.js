const nf0 = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 1 });

export function formatInt(n) {
  if (n == null || Number.isNaN(n)) return '—';
  return nf0.format(n);
}

export const formatNumber = formatInt;

export function formatCompact(n) {
  if (n == null || Number.isNaN(n)) return '—';
  if (Math.abs(n) >= 1e6) return nf1.format(n / 1e6) + ' M';
  if (Math.abs(n) >= 1e3) return nf1.format(n / 1e3) + ' K';
  return nf0.format(n);
}