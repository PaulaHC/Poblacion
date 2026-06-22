export const API_BASE =
  (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_API_URL)
  || '/api';


export const MAP_CONFIG = {
  center: [40.0, -3.7],
  zoom: 6,
  minZoom: 5,
  maxZoom: 12,
  geo: {
    municipiosLow: '/geo/municipios-low.geo.json',
    provincias:    '/geo/provincias.geo.json',
  },
};

export const PANE_ZINDEX = {
  poblacion: 400,
  renta:     410,
  estudios:  420,
  trabajo:   430,
};

export const RAMP_POBLACION = [
  '#EFF4FE', '#D6E4FB', '#A9C5F4',
  '#6E9EE8', '#3B76D6', '#1D4ED8', '#1E3A8A',
];

export const LAYER_STYLE = {
  renta:    { color: '#0F7F5C', label: 'Renta media', unit: '€/persona' },  // verde
  estudios: { color: '#7C3AED', label: 'Estudios superiores', unit: '%' },  // violeta
};

export const CIRCLE_RADIUS = { min: 4, max: 20 };

export const SECTOR_ICONS = {
  industria: {
    label: 'Industria', color: '#B45309',
    svg: '<path d="M2 14h12V7l-4 2.5V7L6 9.5V4H2v10z"/>',
  },
  construccion: {
    label: 'Construcción', color: '#A16207',
    svg: '<path d="M2 13h12v1.5H2V13zm1-2 7.5-7.5 1 1L3.5 12 3 11zm8.5-8L13 4.5 11.5 6 10 4.5 11.5 3z"/>',
  },
  comercio: {
    label: 'Comercio y hostelería', color: '#2563EB',
    svg: '<path d="M3 5h10l-1 3H4L3 5zm0 4h10v5H3V9zm2 1v3h2v-3H5z"/>',
  },
  informacion: {
    label: 'Información y comunicaciones', color: '#0891B2',
    svg: '<path d="M8 2a4 4 0 0 0-4 4c0 1.5 1 2.7 2 3.5V13h4V9.5c1-.8 2-2 2-3.5a4 4 0 0 0-4-4zM6 14h4v1H6v-1z"/>',
  },
  financieras: {
    label: 'Finanzas y seguros', color: '#475569',
    svg: '<path d="M8 2 2 5v1h12V5L8 2zM3 7v5H2v2h12v-2h-1V7h-2v5H9V7H7v5H5V7H3z"/>',
  },
  inmobiliarias: {
    label: 'Actividades inmobiliarias', color: '#9333EA',
    svg: '<path d="M8 2 2 7h2v7h3V9h2v5h3V7h2L8 2z"/>',
  },
  profesionales: {
    label: 'Servicios profesionales', color: '#4F46E5',
    svg: '<path d="M6 3h4v2h3v9H3V5h3V3zm1 1v1h2V4H7z"/>',
  },
  educacion_sanidad: {
    label: 'Educación, sanidad y social', color: '#DB2777',
    svg: '<path d="M8 3 2 6l6 3 4-2v2.5h1V6L8 3zM5 9.5V12c0 1 1.5 2 3 2s3-1 3-2V9.5L8 11 5 9.5z"/>',
  },
  otros_servicios: {
    label: 'Otros servicios', color: '#64748B',
    svg: '<path d="M4 7a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3zm4 0a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3zm4 0a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3z"/>',
  },
  agricultura: {
    label: 'Agricultura', color: '#65A30D',
    svg: '<path d="M3 11a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm8 0a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM4 4h3l1 4h3l1-2 1 .5-1.3 2.5H5L4 5H2V4h2z"/>',
  },
};