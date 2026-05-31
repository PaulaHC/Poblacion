/* ============================================================
   Configuración centralizada.
   ============================================================ */

export const API_BASE =
  (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_API_URL)
  || '/api';

/* ----- Mapa ----- */
export const MAP_CONFIG = {
  // Centro de España peninsular y zoom inicial
  center: [40.0, -3.7],
  zoom: 6,
  minZoom: 5,
  maxZoom: 12,
  // Umbrales de zoom para cambiar nivel de detalle (LOD)
  lod: {
    provincias:    { maxZoom: 7  },
    municipiosLow: { minZoom: 7, maxZoom: 9 },
    municipiosHi:  { minZoom: 9 },
  },
  geo: {
    provincias:    '/geo/provincias.geo.json',
    municipiosLow: '/geo/municipios-low.geo.json',
    municipiosHi:  '/geo/municipios-hi.geo.json',
  },
};

/* ----- Etiquetas humanas ----- */
export const SEXO_LABELS = {
  total:   'Total',
  hombres: 'Hombres',
  mujeres: 'Mujeres',
};

/* ----- Escala secuencial azul para población ----- */
export const RAMP_POBLACION = [
  '#EFF4FE', '#D6E4FB', '#A9C5F4',
  '#6E9EE8', '#3B76D6', '#1D4ED8', '#1E3A8A',
];
