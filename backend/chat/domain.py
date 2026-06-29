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
    agg: str           
    por_sexo: bool      
    label: str        
    unidad: str        


INDICADORES: dict[str, Indicator] = {
    "poblacion":      Indicator("poblacion",      "municipios",     "sum",  True,  "población",               "habitantes"),
    "renta":          Indicator("renta",          "renta",          "mean", False, "renta media",             "€"),
    "esperanza_vida": Indicator("esperanza_vida", "esperanza_vida", "mean", True,  "esperanza de vida",       "años"),
    "edad_mediana":   Indicator("edad_mediana",   "edad_mediana",   "mean", True,  "edad mediana",            "años"),
    "fecundidad":     Indicator("fecundidad",     "fecundidad",     "mean", False, "indicador de fecundidad", ""),
}



GENERICOS = {"provincia", "provincias", "municipio", "municipios",
             "comunidad", "comunidades", "espana", "pais", "lugar", "sitio"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").strip()



_ALIAS_INDICADOR: dict[str, str] = {
    "poblacion": "poblacion", "municipios": "poblacion", "municipio": "poblacion",
    "habitantes": "poblacion", "demografia": "poblacion", "padron": "poblacion",
    "renta": "renta", "ingresos": "renta", "renta media": "renta",
    "esperanza_vida": "esperanza_vida", "esperanza de vida": "esperanza_vida",
    "esperanza": "esperanza_vida",
    "edad_mediana": "edad_mediana", "edad mediana": "edad_mediana", "edad": "edad_mediana",
    "fecundidad": "fecundidad",
    "trabajo": "trabajo", "empleo": "trabajo", "sector": "trabajo", "sectores": "trabajo",
    "empresas": "trabajo", "economia": "trabajo",
}


def resolver_indicador(token: Optional[str]) -> Optional[str]:

    if not token:
        return None
    return _ALIAS_INDICADOR.get(_norm(token))


@dataclass(frozen=True)
class Place:
    nivel: str              
    cod: str                
    nombre: str


# ============================================================
#  Sectores de trabajo (CNAE)
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
_SECTOR_TOTALES = {"total", "total servicios", "todos", "todas"}

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
    if n in _SECTOR_TOTALES:
        return None
    for clave, agujas in _SECTOR_CANON:
        if any(a in n for a in agujas):
            return clave
    return "otros_servicios"


def fmt(value: float, *, entero: bool) -> str:
    if entero:
        return f"{round(value):,}".replace(",", ".")
    return f"{value:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")