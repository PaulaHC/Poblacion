from difflib import get_close_matches
from typing import Optional

from fastapi import HTTPException

import db
from .domain import Indicator, Place, SECTOR_LABELS, canon_sector


_SEXO_AGREGADO_REGEX = r"/^(Total|Ambos sexos|Ambos)$/"


class InfluxStats:

    # -- Resolución de lugares --------------------------------------
    def resolve_place(self, name: str) -> Optional[Place]:
        if not name:
            return None
        objetivo = db.normaliza(name)

        idx_prov = {db.normaliza(p["nombre"]): p for p in db._provincias()}
        m = get_close_matches(objetivo, list(idx_prov.keys()), n=1, cutoff=0.82)
        if m:
            p = idx_prov[m[0]]
            return Place(nivel="provincia", cod=p["id"], nombre=p["nombre"])

        idx_mun = {db.normaliza(mu["nombre"]): mu for mu in db._municipios()}
        m = get_close_matches(objetivo, list(idx_mun.keys()), n=1, cutoff=0.82)
        if m:
            mu = idx_mun[m[0]]
            return Place(nivel="municipio", cod=mu["id"], nombre=mu["nombre"])

        return None

    # -- Consultas de datos -----------------------------------------
    def fetch_value(self, indicator: Indicator, *,
                    place: Optional[Place], year: int) -> list[float]:
        flux, params = self._build_flux(indicator, place=place, year=year, modo="valor")
        filas = self._run(flux, params)
        return [float(f["_value"]) for f in filas if f.get("_value") is not None]

    def fetch_ranking(self, indicator: Indicator, *,
                      place: Optional[Place], year: int,
                      order: str) -> list[tuple[str, float]]:
        flux, params = self._build_flux(indicator, place=place, year=year,
                                        modo="ranking", orden=order)
        filas = self._run(flux, params)
        return [(f.get("municipio") or f.get("provincia"), float(f["_value"]))
                for f in filas if f.get("_value") is not None]

    def fetch_trabajo(self, *, place: Optional[Place], year: int,
                      top: int = 6) -> list[tuple[str, float]]:
        params: dict = {"bucket": db.INFLUX_BUCKET, "stop": f"{year}-12-31T23:59:59Z"}
        scope = ""
        if place:
            col = "cod_municipio" if place.nivel == "municipio" else "cod_provincia"
            scope = f"and r.{col} == ${{cod}}"
            params["cod"] = place.cod

        flux = (
            f"from(bucket: ${{bucket}}) "
            f"|> range(start: 1990-01-01T00:00:00Z, stop: time(v: ${{stop}})) "
            f'|> filter(fn: (r) => r._measurement == "ine_stats" and r._field == "valor" '
            f'and r.subgrupo == "trabajo" {scope}) '
            f'|> group(columns: ["cod_municipio", "sector"]) |> last() '
            f'|> keep(columns: ["sector", "_value"])'
        )
        filas = self._run(flux, params)

        agg: dict[str, float] = {}
        for f in filas:
            clave = canon_sector(f.get("sector") or "")
            valor = f.get("_value")
            if clave is None or valor is None:
                continue
            agg[clave] = agg.get(clave, 0.0) + float(valor)

        ordenado = sorted(agg.items(), key=lambda kv: kv[1], reverse=True)
        return [(SECTOR_LABELS.get(k, k), v) for k, v in ordenado[:top]]

    # -- Detalle Flux -------------------------------------
    @staticmethod
    def _run(flux: str, params: dict) -> list:
        try:
            filas = [dict(r.values) for t in db.query(flux, params) for r in t.records]
            db.logger.info("[chat] flux -> %d filas | %s", len(filas), " ".join(flux.split()))
            return filas
        except HTTPException as exc:
            if "_value" in str(exc.detail):
                return []
            raise

    @staticmethod
    def _build_flux(indicator: Indicator, *, place: Optional[Place],
                    year: int, modo: str, orden: str = "desc") -> tuple[str, dict]:
        params: dict = {"bucket": db.INFLUX_BUCKET, "subgrupo": indicator.subgrupo,
                        "stop": f"{year}-12-31T23:59:59Z"}

        sexo = f"and r.sexo =~ {_SEXO_AGREGADO_REGEX}" if indicator.por_sexo else ""

        scope = ""
        if place:
            col = "cod_municipio" if place.nivel == "municipio" else "cod_provincia"
            scope = f"and r.{col} == ${{cod}}"
            params["cod"] = place.cod

        entity = "cod_provincia" if indicator.subgrupo == "renta" else "cod_municipio"
        agg = "sum" if indicator.agg == "sum" else "mean"

        base = (
            f"from(bucket: ${{bucket}}) "
            f"|> range(start: 1990-01-01T00:00:00Z, stop: time(v: ${{stop}})) "
            f'|> filter(fn: (r) => r._measurement == "ine_stats" '
            f'and r._field == "valor" and r.subgrupo == ${{subgrupo}} '
            f"{sexo} {scope}) "
            f'|> group(columns: ["{entity}", "municipio", "provincia"]) '
            f"|> last()"
        )

        if modo == "ranking":
            desc = "true" if orden == "desc" else "false"
            col_group = "municipio" if (place and place.nivel == "provincia") else "provincia"
            flux = (base + f' |> group(columns:["{col_group}"]) |> {agg}() |> group() '
                           f'|> sort(columns:["_value"], desc:{desc}) |> limit(n:50)')
        else:
            flux = base + ' |> group()'
        return flux, params