from dataclasses import dataclass
from typing import Optional
import unicodedata


# ============================================================
#  Indicador
# ============================================================
@dataclass(frozen=True)
class Indicator:
    key: str
    subgrupo: str
    agg: str                       # "sum" | "mean"
    por_sexo: bool                 # tiene tag sexo -> filtrar al total
    label: str
    unidad: str
    categoria_tag: Optional[str] = None   # si es distribución: tag por el que reparte
    grupo_edad: bool = False              # tiene tag grupo_edad -> reducir al total


# --- Indicadores de VALOR (una cifra por municipio/provincia) ---------
# --- Indicadores de DISTRIBUCIÓN (reparto por categoría) --------------
INDICADORES: dict[str, Indicator] = {
    "poblacion":      Indicator("poblacion",      "municipios",     "sum",  True,  "población",               "habitantes"),
    "renta":          Indicator("renta",          "renta",          "mean", False, "renta media",             "€"),
    "esperanza_vida": Indicator("esperanza_vida", "esperanza_vida", "mean", True,  "esperanza de vida",       "años"),
    "edad_mediana":   Indicator("edad_mediana",   "edad_mediana",   "mean", True,  "edad mediana",            "años"),
    "fecundidad":     Indicator("fecundidad",     "fecundidad",     "mean", False, "indicador de fecundidad", ""),
    "natalidad":      Indicator("natalidad",      "natalidad",      "mean", False, "tasa de natalidad",       ""),

    # Distribuciones
    "trabajo":     Indicator("trabajo",     "trabajo",     "sum", False, "actividad económica", "empresas",
                             categoria_tag="sector"),
    "estudios":    Indicator("estudios",    "estudios",    "sum", True,  "nivel de estudios",   "personas",
                             categoria_tag="nivel_estudio", grupo_edad=True),
    "estado_civil":Indicator("estado_civil","estadoCivil", "sum", True,  "estado civil",        "personas",
                             categoria_tag="estado_civil",  grupo_edad=True),
    "migracion":   Indicator("migracion",   "migracion",   "sum", True,  "migración por nacionalidad", "personas",
                             categoria_tag="nacionalidad",  grupo_edad=True),
    "mortalidad":  Indicator("mortalidad",  "mortalidad",  "mean", True, "mortalidad por edad", "",
                             categoria_tag="grupo_edad"),
}


GENERICOS = {"provincia", "provincias", "municipio", "municipios",
             "comunidad", "comunidades", "espana", "pais", "lugar", "sitio"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").strip()


_TOTAL_TOKENS = ("total", "ambos", "todas", "todos")


def es_total(v: Optional[str]) -> bool:
    """True si el valor de un tag representa un 'Total'/'Ambos sexos'/'Todas las
    edades'. Detecta por el nombre, sin depender del literal exacto del INE."""
    n = _norm(v or "")
    return any(t in n for t in _TOTAL_TOKENS)


_ALIAS_INDICADOR: dict[str, str] = {
    "poblacion": "poblacion", "municipios": "poblacion", "municipio": "poblacion",
    "habitantes": "poblacion", "demografia": "poblacion", "padron": "poblacion",
    "renta": "renta", "ingresos": "renta", "renta media": "renta",
    "esperanza_vida": "esperanza_vida", "esperanza de vida": "esperanza_vida",
    "esperanza": "esperanza_vida",
    "edad_mediana": "edad_mediana", "edad mediana": "edad_mediana", "edad": "edad_mediana",
    "fecundidad": "fecundidad",
    "natalidad": "natalidad", "nacimientos": "natalidad", "tasa de natalidad": "natalidad",
    "mortalidad": "mortalidad", "defunciones": "mortalidad", "muertes": "mortalidad",
    "trabajo": "trabajo", "empleo": "trabajo", "sector": "trabajo", "sectores": "trabajo",
    "sector de trabajo": "trabajo", "actividad economica": "trabajo", "trabajos": "trabajo",
    "empresas": "trabajo", "economia": "trabajo", "actividad": "trabajo", "cnae": "trabajo",
    "estudios": "estudios", "nivel de estudios": "estudios", "educacion": "estudios",
    "formacion": "estudios", "estudio": "estudios",
    "estado civil": "estado_civil", "estado_civil": "estado_civil", "estadocivil": "estado_civil",
    "casados": "estado_civil", "solteros": "estado_civil", "civil": "estado_civil",
    "migracion": "migracion", "migraciones": "migracion", "extranjeros": "migracion",
    "nacionalidad": "migracion", "inmigracion": "migracion",
}


# Alias ordenados por longitud (los más específicos primero) para el fallback.
_ALIAS_ORDENADOS = sorted(_ALIAS_INDICADOR.items(), key=lambda kv: len(kv[0]), reverse=True)


def resolver_indicador(token: Optional[str]) -> Optional[str]:
    """Resuelve el indicador tolerando frases: primero coincidencia exacta y, si
    no, busca cualquier alias contenido en el texto (p. ej. 'sector de trabajo
    mayoritario' -> 'trabajo'). No depende del literal exacto del modelo."""
    if not token:
        return None
    n = _norm(token)
    if n in _ALIAS_INDICADOR:
        return _ALIAS_INDICADOR[n]
    for alias, clave in _ALIAS_ORDENADOS:
        if alias in n:
            return clave
    return None


@dataclass(frozen=True)
class Place:
    nivel: str
    cod: str
    nombre: str


# ============================================================
#  Etiquetas legibles de sectores de trabajo (CNAE)
# ============================================================
_SECTOR_CANON = [
    ("industria",         ("industria",)),
    ("construccion",      ("construccion",)),
    ("comercio",          ("comercio", "transporte", "hosteleria")),
    ("informacion",       ("informacion", "comunicacion")),
    ("financieras",       ("financ", "seguros")),
    ("inmobiliarias",     ("inmobiliar",)),
    ("profesionales",     ("profesional", "tecnic")),
    ("educacion_sanidad", ("educacion", "sanidad", "social")),
    ("otros_servicios",   ("otros servicios", "servicios personales")),
]

SECTOR_LABELS = {
    "industria":         "Industria",
    "construccion":      "Construcción",
    "comercio":          "Comercio y hostelería",
    "informacion":       "Información y comunicaciones",
    "financieras":       "Finanzas y seguros",
    "inmobiliarias":     "Actividades inmobiliarias",
    "profesionales":     "Servicios profesionales",
    "educacion_sanidad": "Educación, sanidad y social",
    "otros_servicios":   "Otros servicios",
}


def canon_sector(nombre: str) -> Optional[str]:
    n = _norm(nombre)
    if es_total(n) or n == "total servicios":
        return None
    for clave, agujas in _SECTOR_CANON:
        if any(a in n for a in agujas):
            return clave
    return "otros_servicios"


def etiqueta_categoria(indicator: Indicator, valor: str) -> str:
    """Etiqueta legible de una categoría. Para trabajo agrupa por CNAE canónico;
    para el resto, devuelve el propio texto del INE (ya es legible)."""
    if indicator.categoria_tag == "sector":
        clave = canon_sector(valor)
        return SECTOR_LABELS.get(clave, valor) if clave else valor
    return valor


def fmt(value: float, *, entero: bool) -> str:
    if entero:
        return f"{round(value):,}".replace(",", ".")
    return f"{value:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")