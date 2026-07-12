"""
Resolución difusa de lugares (municipios/provincias) -> Place.
Reutiliza los catálogos y la normalización de db.py. Solo Python, sin LLM.

El índice normalizado se construye una única vez (primera llamada) y se cachea
en memoria: las siguientes resoluciones son inmediatas.
"""
from difflib import get_close_matches
from typing import Optional

import db
from .domain import Place

# nombre_normalizado -> (cod, nombre_oficial). Se construyen una sola vez.
_PROVINCIAS: dict[str, tuple[str, str]] = {}
_MUNICIPIOS: dict[str, tuple[str, str]] = {}
_CLAVES_PROV: list[str] = []
_MUNICIPIOS_KEYS: list[str] = []
_CARGADO = False


def _cargar_catalogos() -> None:
    global _CARGADO
    if _CARGADO:
        return
    for p in db._provincias():                   # [{"id","nombre","comunidad"}, ...]
        _PROVINCIAS[db.normaliza(p["nombre"])] = (p["id"], p["nombre"])
    for m in db._municipios():                   # [{"id","nombre",...}, ...]
        _MUNICIPIOS[db.normaliza(m["nombre"])] = (m["id"], m["nombre"])
    _CLAVES_PROV.extend(_PROVINCIAS.keys())
    _MUNICIPIOS_KEYS.extend(_MUNICIPIOS.keys())
    _CARGADO = True


def resolver_lugar(nombre: str) -> Optional[Place]:
    """Devuelve un Place (provincia primero, luego municipio) o None."""
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

    for catalogo, keys, nivel in (
        (_PROVINCIAS, _CLAVES_PROV, "provincia"),
        (_MUNICIPIOS, _MUNICIPIOS_KEYS, "municipio"),
    ):
        cand = get_close_matches(clave, keys, n=1, cutoff=0.8)
        if cand:
            cod, oficial = catalogo[cand[0]]
            return Place(nivel=nivel, cod=cod, nombre=oficial)
    return None