from typing import Literal, Optional

from langchain_core.tools import tool

from .adapters import InfluxStats
from .domain import INDICADORES, Indicator, fmt, resolver_indicador
from .resolvers import resolver_lugar

_stats = InfluxStats()


def _norm_orden(orden: str) -> str:
    o = (orden or "").lower().strip()
    if o in ("asc", "ascendente", "menor", "menos", "bajo", "pocos"):
        return "asc"
    return "desc"


def _formatear(indicador: Indicator, valor: float) -> str:
    entero = indicador.agg == "sum" or indicador.unidad == "€"
    return fmt(valor, entero=entero)


@tool
def obtener_dato(indicador: str, lugar: str, anio: Optional[int] = None) -> dict:
    """Obtiene el valor de un indicador para un lugar y año determinados."""
    clave = resolver_indicador(indicador)
    if clave not in INDICADORES:
        return {"ok": False, "motivo": "indicador_desconocido", "indicador": indicador}
    ind = INDICADORES[clave]
    if ind.categoria_tag:
        return {"ok": False, "motivo": "usa_distribucion", "indicador": clave}

    place = resolver_lugar(lugar)
    if place is None:
        return {"ok": False, "motivo": "lugar_no_encontrado", "lugar": lugar}

    filas = _stats.consultar(ind, place=place, modo="valor", anio=anio)
    if not filas:
        return {"ok": False, "motivo": "sin_datos", "lugar": place.nombre}

    f = filas[0]
    return {
        "ok": True,
        "indicador": ind.label,
        "lugar": place.nombre,
        "anio": f.get("anio"),
        "cifra": _formatear(ind, f["valor"]),
        "unidad": ind.unidad,
    }


@tool
def hacer_ranking(
    indicador: str,
    orden: Literal["desc", "asc"] = "desc",
    ambito: Optional[str] = None,
    limite: int = 10,
) -> dict:
    """Genera un ranking de lugares ordenado por un indicador."""
    clave = resolver_indicador(indicador)
    if clave not in INDICADORES:
        return {"ok": False, "motivo": "indicador_desconocido", "indicador": indicador}
    ind = INDICADORES[clave]
    if ind.categoria_tag:
        return {"ok": False, "motivo": "usa_distribucion", "indicador": clave}

    place = resolver_lugar(ambito) if ambito else None
    if ambito and place is None:
        return {"ok": False, "motivo": "lugar_no_encontrado", "lugar": ambito}

    filas = _stats.consultar(ind, place=place, modo="ranking", orden=_norm_orden(orden))
    if not filas:
        return {"ok": False, "motivo": "sin_datos"}

    n = max(1, min(int(limite or 10), 50))
    top = [
        {"nombre": f["nombre"], "cifra": _formatear(ind, f["valor"])}
        for f in filas[:n]
        if f.get("nombre")
    ]
    return {"ok": True, "indicador": ind.label, "orden": _norm_orden(orden),
            "unidad": ind.unidad, "filas": top}


@tool
def ver_distribucion(indicador: str, lugar: str, anio: Optional[int] = None) -> dict:
    """Muestra la distribución por categorías de un indicador."""
    clave = resolver_indicador(indicador)
    if clave not in INDICADORES:
        return {"ok": False, "motivo": "indicador_desconocido", "indicador": indicador}
    ind = INDICADORES[clave]
    if not ind.categoria_tag:
        return {"ok": False, "motivo": "no_es_distribucion", "indicador": clave}

    place = resolver_lugar(lugar)
    if place is None:
        return {"ok": False, "motivo": "lugar_no_encontrado", "lugar": lugar}

    filas = _stats.distribucion(ind, place=place, anio=anio)
    if not filas:
        return {"ok": False, "motivo": "sin_datos", "lugar": place.nombre}

    desglose = [{"categoria": r["categoria"], "cifra": _formatear(ind, r["valor"])}
                for r in filas]
    return {
        "ok": True,
        "indicador": ind.label,
        "lugar": place.nombre,
        "unidad": ind.unidad,
        "mayoritaria": desglose[0],
        "desglose": desglose,
    }


TOOLS = [obtener_dato, hacer_ranking, ver_distribucion]