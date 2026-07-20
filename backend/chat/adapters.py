import json
from typing import Optional

from fastapi import HTTPException

import db
from .domain import (Indicator, Place, es_total, etiqueta_categoria)


_SEXO_AGREGADO_REGEX = r"/^(Total|Ambos sexos|Ambos)$/"


def _cols(nombres: list[str]) -> str:
    return json.dumps(nombres)


class InfluxStats:

    # -- Valor simple (una cifra) -----------------------------------
    def consultar(self, indicator: Indicator, *, place: Optional[Place] = None,
                  modo: str = "valor", orden: str = "desc",
                  anio: Optional[int] = None) -> list[dict]:
        year = anio or db.DEFAULT_ANIO
        flux, params = self._build_flux(indicator, place=place, year=year,
                                        modo=modo, orden=orden)
        rows = self._run(flux, params)

        if modo == "valor":
            valores = [float(f["_value"]) for f in rows if f.get("_value") is not None]
            if not valores:
                return []
            total = sum(valores) if indicator.agg == "sum" else sum(valores) / len(valores)
            nombre = place.nombre if place else (
                rows[0].get("municipio") or rows[0].get("provincia") or rows[0].get("comunidad"))
            return [{"valor": total, "nombre": nombre, "anio": year}]

        filas = []
        for f in rows:
            valor = f.get("_value")
            if valor is None:
                continue
            filas.append({
                "valor": float(valor),
                "nombre": f.get("municipio") or f.get("provincia") or f.get("comunidad"),
                "anio": year,
            })
        return filas

    def distribucion(self, indicator: Indicator, *, place: Optional[Place] = None,
                     anio: Optional[int] = None) -> list[dict]:
        year = anio or db.DEFAULT_ANIO
        tag = indicator.categoria_tag
        if not tag:
            return []

        params: dict = {"bucket": db.INFLUX_BUCKET, "subgrupo": indicator.subgrupo,
                        "stop": f"{year}-12-31T23:59:59Z"}
        scope = ""
        if place:
            col = "cod_municipio" if place.nivel == "municipio" else "cod_provincia"
            scope = f"and r.{col} == ${{cod}}"
            params["cod"] = place.cod

        group_cols = ["cod_municipio", tag]
        if indicator.por_sexo and tag != "sexo":
            group_cols.append("sexo")
        if indicator.grupo_edad and tag != "grupo_edad":
            group_cols.append("grupo_edad")
        keep = group_cols + ["_value"]

        flux = (
            f"from(bucket: ${{bucket}}) "
            f"|> range(start: 1990-01-01T00:00:00Z, stop: time(v: ${{stop}})) "
            f'|> filter(fn: (r) => r._measurement == "ine_stats" and r._field == "valor" '
            f"and r.subgrupo == ${{subgrupo}} {scope}) "
            f"|> group(columns: {_cols(group_cols)}) |> last() "
            f"|> keep(columns: {_cols(keep)})"
        )
        rows = self._run(flux, params)
        return self._reducir(rows, indicator)

    @staticmethod
    def _reducir(rows: list[dict], indicator: Indicator) -> list[dict]:
        tag = indicator.categoria_tag

        if indicator.por_sexo and tag != "sexo":
            tot = [r for r in rows if es_total(r.get("sexo"))]
            rows = tot if tot else rows
        if indicator.grupo_edad and tag != "grupo_edad":
            tot = [r for r in rows if es_total(r.get("grupo_edad"))]
            rows = tot if tot else rows

        sumas: dict[str, float] = {}
        cuentas: dict[str, int] = {}
        for r in rows:
            cat = r.get(tag) or ""
            valor = r.get("_value")
            if valor is None or es_total(cat):
                continue
            etiqueta = etiqueta_categoria(indicator, cat)
            sumas[etiqueta] = sumas.get(etiqueta, 0.0) + float(valor)
            cuentas[etiqueta] = cuentas.get(etiqueta, 0) + 1

        media = indicator.agg == "mean"
        items = [(k, (v / cuentas[k]) if media else v) for k, v in sumas.items()]
        items.sort(key=lambda kv: kv[1], reverse=True)
        return [{"categoria": k, "valor": v} for k, v in items]

    # -- Detalle Flux -------------------------------------
    @staticmethod
    def _run(flux: str, params: dict) -> list[dict]:
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