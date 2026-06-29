import asyncio

import db
from .adapters import InfluxStats
from .domain import GENERICOS, INDICADORES, fmt, resolver_indicador


class InfluxRetriever:

    def __init__(self) -> None:
        self._stats = InfluxStats()

    async def __call__(self, intent: dict) -> list[dict]:
        return await asyncio.to_thread(self._recuperar, intent)

    def _recuperar(self, intent: dict) -> list[dict]:
        raw = intent.get("indicador")
        key = resolver_indicador(raw)
        if key is None:
            if raw:
                return []
            key = "poblacion"

        nombre = intent.get("lugar")
        place = None
        if nombre and db.normaliza(nombre) not in GENERICOS:
            place = self._stats.resolve_place(nombre)
            if place is None:               
                return []

        try:
            year = int(intent["anio"]) if intent.get("anio") is not None else db.DEFAULT_ANIO
        except (ValueError, TypeError):
            year = db.DEFAULT_ANIO

        place_name = place.nombre if place else "España"

        if key == "trabajo":
            sectores = self._stats.fetch_trabajo(place=place, year=year)
            if not sectores:
                return []
            return [{"lugar": place_name, "anio": year, "sector": s,
                     "valor": round(v), "texto": s, "unidad": "empresas"}
                    for s, v in sectores]

        indicator = INDICADORES[key]
        unidad = indicator.unidad
        entero = indicator.agg == "sum" or unidad == "€"

        def _fila(lugar: str, valor: float) -> dict:
            texto = f"{fmt(valor, entero=entero)} {unidad}".strip()
            return {"lugar": lugar, "anio": year, "valor": round(valor, 1),
                    "texto": texto, "unidad": unidad, "etiqueta": indicator.label}

        # Ranking ---------------------------------------------------
        if intent.get("ranking"):
            rows = self._stats.fetch_ranking(
                indicator, place=place, year=year, order=intent.get("orden", "desc"))
            return [_fila(n, v) for n, v in rows[:10]]

        # Valor único ----------------------------------------------
        values = self._stats.fetch_value(indicator, place=place, year=year)
        if not values:
            return []
        total = sum(values) if indicator.agg == "sum" else sum(values) / len(values)
        return [_fila(place_name, total)]