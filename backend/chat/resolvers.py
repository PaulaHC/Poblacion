from difflib import get_close_matches
from typing import Optional

import db
from .domain import Place

_PROVINCIAS: dict[str, tuple[str, str]] = {}
_MUNICIPIOS: dict[str, tuple[str, str]] = {}
_CLAVES_PROV: list[str] = []
_MUNICIPIOS_KEYS: list[str] = []
_CARGADO = False


def _cargar_catalogos() -> None:
    global _CARGADO
    if _CARGADO:
        return
    for p in db._provincias():                  
        _PROVINCIAS[db.normaliza(p["nombre"])] = (p["id"], p["nombre"])
    for m in db._municipios():                   
        _MUNICIPIOS[db.normaliza(m["nombre"])] = (m["id"], m["nombre"])
    _CLAVES_PROV.extend(_PROVINCIAS.keys())
    _MUNICIPIOS_KEYS.extend(_MUNICIPIOS.keys())
    _CARGADO = True


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

    for catalogo, keys, nivel in (
        (_PROVINCIAS, _CLAVES_PROV, "provincia"),
        (_MUNICIPIOS, _MUNICIPIOS_KEYS, "municipio"),
    ):
        cand = get_close_matches(clave, keys, n=1, cutoff=0.8)
        if cand:
            cod, oficial = catalogo[cand[0]]
            return Place(nivel=nivel, cod=cod, nombre=oficial)
    return None