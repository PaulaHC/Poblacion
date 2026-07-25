"""Preclasificador determinista: detecta consultas autocontenidas y construye
la tool call en Python, sin pasar por el router LLM."""
import re
import uuid
from typing import Optional

from langchain_core.messages import AIMessage

import db
from .domain import INDICADORES, resolver_indicador
from .resolvers import _cargar_catalogos, _PROVINCIAS, _MUNICIPIOS

_RANKING = re.compile(
    r"\b(ranking|top|mayor(es)?|menor(es)?|mas|menos|m[aá]s|primer[oa]s?|"
    r"[uú]ltim[oa]s?|ordena\w*|list(a|ado))\b", re.I)
_ASC = re.compile(r"\b(menos|menor(es)?|m[ií]nim\w+|baj[oa]s?|[uú]ltim)\w*", re.I)
_ANIO = re.compile(r"\b(19|20)\d{2}\b")
_LIMITE = re.compile(
    r"\btop\s*(\d{1,2})|\b(\d{1,2})\s+(municipios|provincias|lugares)\b", re.I)
_NIVEL_MUNI = re.compile(r"\bmunicipi|\bpueblos?\b|\blocalidad", re.I)
_NIVEL_PROV = re.compile(r"\bprovinci", re.I)


def _detectar_lugar(texto_norm: str) -> Optional[str]:
    """Nombre de lugar mas largo contenido en la frase (evita falsos cortos)."""
    _cargar_catalogos()
    mejor = ""
    for clave in list(_PROVINCIAS) + list(_MUNICIPIOS):
        if len(clave) > len(mejor) and len(clave) >= 4 and clave in texto_norm:
            mejor = clave
    return mejor or None


def preclasificar(texto: str) -> Optional[AIMessage]:
    """Devuelve un AIMessage con la tool call ya construida, o None si la
    consulta no es autocontenida y debe ir al LLM."""
    n = db.normaliza(texto)

    clave = resolver_indicador(n)
    if clave is None:
        return None
    ind = INDICADORES[clave]

    m_anio = _ANIO.search(n)
    anio = int(m_anio.group()) if m_anio else None

    es_ranking = bool(_RANKING.search(n)) and not ind.categoria_tag
    lugar = _detectar_lugar(n)

    if es_ranking:
        orden = "asc" if _ASC.search(n) else "desc"
        m_lim = _LIMITE.search(n)
        grupos = m_lim.groups() if m_lim else ()
        limite = int(next((g for g in grupos if g and g.isdigit()), 10))
        args = {"indicador": clave, "orden": orden, "limite": limite}
        if lugar:
            args["ambito"] = lugar
        if _NIVEL_MUNI.search(n):
            args["nivel"] = "municipio"
        elif _NIVEL_PROV.search(n):
            args["nivel"] = "provincia"
        if anio:
            args["anio"] = anio
        tool = "hacer_ranking"
    elif lugar:
        args = {"indicador": clave, "lugar": lugar}
        if anio:
            args["anio"] = anio
        tool = "ver_distribucion" if ind.categoria_tag else "obtener_dato"
    else:
        return None  # indicador sin lugar ni ranking -> ambiguo, al LLM

    return AIMessage(content="", tool_calls=[{
        "name": tool, "args": args, "id": f"pre-{uuid.uuid4().hex[:8]}",
    }])
