"""Resolución de nombres de lugar (provincia/municipio) a códigos INE.

Los catálogos se cargan desde InfluxDB y se refrescan cada db.CACHE_TTL
segundos para incorporar los datos nuevos del ETL nocturno sin reiniciar
el backend.
"""
import time
from difflib import get_close_matches
from typing import Optional

import db
from .domain import Place

_PROVINCIAS: dict[str, tuple[str, str]] = {}
_MUNICIPIOS: dict[str, tuple[str, str]] = {}
_CARGA_TS: float = 0.0


def _cargar_catalogos(force: bool = False) -> None:
    global _CARGA_TS
    ahora = time.monotonic()
    if _PROVINCIAS and not force and (ahora - _CARGA_TS) < db.CACHE_TTL:
        return

    provincias = {db.normaliza(p["nombre"]): (p["id"], p["nombre"])
                  for p in db._provincias()}
    municipios = {db.normaliza(m["nombre"]): (m["id"], m["nombre"])
                  for m in db._municipios()}

    # Si Influx devuelve vacío (arranque, fallo transitorio), conserva el
    # catálogo anterior en lugar de dejar el chat sin lugares.
    if not provincias and _PROVINCIAS:
        return

    _PROVINCIAS.clear(); _PROVINCIAS.update(provincias)
    _MUNICIPIOS.clear(); _MUNICIPIOS.update(municipios)
    _CARGA_TS = ahora


def resolver_lugar(nombre: str) -> Optional[Place]:
    if not nombre:
        return None
    _cargar_catalogos()
    clave = db.normaliza(nombre)

    if clave in _PROVINCIAS:
        cod, oficial = _PROVINCIAS[clave]
        return Place(nivel="provincia", cod=cod, nombre=oficial)
    if clave in _MUNICIPIOS:
        cod, oficial = _MUNICIPIOS[clave]
        return Place(nivel="municipio", cod=cod, nombre=oficial)

    for catalogo, nivel in ((_PROVINCIAS, "provincia"),
                            (_MUNICIPIOS, "municipio")):
        cand = get_close_matches(clave, list(catalogo), n=1, cutoff=0.8)
        if cand:
            cod, oficial = catalogo[cand[0]]
            return Place(nivel=nivel, cod=cod, nombre=oficial)
    return None
