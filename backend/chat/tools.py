"""
Herramientas acotadas del agente (nivel 2).

Tres herramientas, cada una para un tipo de pregunta:
  - obtener_dato: una cifra (población, renta, esperanza, edad, fecundidad, natalidad).
  - hacer_ranking: ordenar municipios/provincias por una de esas cifras.
  - ver_distribucion: reparto por categoría (trabajo/sector, estudios, estado
    civil, migración por nacionalidad): categoría mayoritaria + desglose.

El LLM elige la herramienta y rellena los huecos; el indicador se valida contra
INDICADORES, el lugar pasa por difflib, el Flux lo monta Python y el número lo
formatea fmt(). El modelo nunca emite Flux ni cifras crudas.
"""
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
    """Entero si el indicador suma o si la unidad es dinero; decimal si no."""
    entero = indicador.agg == "sum" or indicador.unidad == "€"
    return fmt(valor, entero=entero)


@tool
def obtener_dato(indicador: str, lugar: str, anio: Optional[int] = None) -> dict:
    """Devuelve UNA cifra de un indicador demográfico para un municipio o provincia.

    Úsala para: población, renta, esperanza de vida, edad mediana, fecundidad,
    natalidad. NO la uses para repartos por categoría (trabajo, estudios, estado
    civil, migración): para eso está ver_distribucion.

    lugar: municipio o provincia (se corrige si está mal escrito).
    anio: año concreto; si se omite, usa el último dato disponible.
    """
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
    """Ranking de municipios (o provincias) por una cifra simple (población,
    renta, esperanza, edad, fecundidad, natalidad).

    orden: 'desc' de mayor a menor, 'asc' de menor a mayor.
    ambito: si es una provincia, rankea sus municipios; si se omite, rankea provincias.
    limite: nº de filas (máx. 50).
    """
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
    """Reparto por categoría de un indicador de distribución, para un municipio o
    provincia. Úsala para: trabajo/sector económico, nivel de estudios, estado
    civil, migración por nacionalidad.

    Devuelve la categoría mayoritaria y el desglose completo ordenado. Menciona
    la mayoritaria por defecto; da el desglose solo si el usuario lo pide.
    """
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