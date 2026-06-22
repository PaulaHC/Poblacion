import json
import logging
import os
import re
import unicodedata
from difflib import get_close_matches
from functools import lru_cache
from typing import Any, Optional

import httpx
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from influxdb_client import InfluxDBClient

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("poview.backend")

# ---- Configuración de InfluxDB -------------------------------------
INFLUX_URL    = os.environ.get("INFLUXDB_URL",    "http://influxdb:8086")
INFLUX_TOKEN  = os.environ.get("INFLUXDB_TOKEN",  "")
INFLUX_ORG    = os.environ.get("INFLUXDB_ORG",    "tfm_rural")
INFLUX_BUCKET = os.environ.get("INFLUXDB_BUCKET", "poblacion_municipios")
CORS_ORIGINS  = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",")]

# ---- Configuración de Ollama --------------------------------------
OLLAMA_URL     = os.environ.get("OLLAMA_URL",     "http://host.docker.internal:11434")
OLLAMA_MODEL   = os.environ.get("OLLAMA_MODEL",   "qwen3:8b")
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "120"))

SEXO_MAP = {"total": "Total", "hombres": "Hombres", "mujeres": "Mujeres"}


DEFAULT_ANIO = int(os.environ.get("DEFAULT_ANIO", "2025"))

@lru_cache(maxsize=1)
def get_client() -> InfluxDBClient:
    if not INFLUX_TOKEN:
        raise RuntimeError("Falta INFLUXDB_TOKEN en el entorno")
    return InfluxDBClient(
        url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG, timeout=60_000
    )


_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _escape_flux_string(s: str) -> str:
    return (
        s.replace("\\", "\\\\")
         .replace('"', '\\"')
         .replace("\n", "\\n")
         .replace("\r", "\\r")
         .replace("\t", "\\t")
    )


def _render_flux(flux: str, params: dict[str, Any]) -> str:
    def repl(m: re.Match) -> str:
        key = m.group(1)
        if key not in params:
            raise KeyError(f"Placeholder ${{{key}}} sin valor en params")
        v = params[key]
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, str):
            return f'"{_escape_flux_string(v)}"'
        return str(v)
    return _PLACEHOLDER.sub(repl, flux)


def query(flux: str, params: Optional[dict] = None):
    rendered = _render_flux(flux, params or {})
    try:
        return get_client().query_api().query(rendered)
    except Exception as exc:
        logger.exception("Influx query falló")
        raise HTTPException(status_code=502, detail=f"Influx error: {exc}") from exc


app = FastAPI(title="Poview backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# =================================================================

@app.get("/api/comunidades")
def list_comunidades() -> list[dict]:
    flux = '''
    import "influxdata/influxdb/schema"
    schema.tagValues(
      bucket: ${bucket},
      tag: "comunidad",
      predicate: (r) => r._measurement == "ine_stats" and r.subgrupo == "municipios",
      start: -30y
    )
    '''
    tables = query(flux, {"bucket": INFLUX_BUCKET})
    nombres: set[str] = set()
    for table in tables:
        for record in table.records:
            v = record.get_value()
            if v and v != "Desconocida":
                nombres.add(v)
    return [{"id": n, "nombre": n} for n in sorted(nombres)]


@app.get("/api/provincias")
def list_provincias(comunidad: Optional[str] = None) -> list[dict]:
    return _provincias(comunidad)


def _provincias(comunidad: Optional[str] = None) -> list[dict]:
    predicate_extra = ""
    params1: dict = {"bucket": INFLUX_BUCKET}
    if comunidad:
        predicate_extra = "and r.comunidad == ${ccaa}"
        params1["ccaa"] = comunidad

    flux1 = f'''
    import "influxdata/influxdb/schema"
    schema.tagValues(
      bucket: ${{bucket}},
      tag: "cod_provincia",
      predicate: (r) => r._measurement == "ine_stats"
                   and r.subgrupo == "municipios"
                   {predicate_extra},
      start: -30y
    )
    '''
    tables1 = query(flux1, params1)
    codigos: set[str] = set()
    for table in tables1:
        for record in table.records:
            v = record.get_value()
            if v:
                codigos.add(v)
    if not codigos:
        return []

    or_list = " or ".join(
        f'r.cod_provincia == "{_escape_flux_string(c)}"' for c in codigos
    )
    flux2 = f'''
    from(bucket: ${{bucket}})
      |> range(start: -30y)
      |> filter(fn: (r) => r._measurement == "ine_stats"
                       and r.subgrupo == "municipios"
                       and r._field == "valor"
                       and ({or_list}))
      |> group(columns: ["cod_provincia", "provincia", "comunidad"])
      |> first()
    '''
    tables2 = query(flux2, {"bucket": INFLUX_BUCKET})
    seen: dict[str, dict] = {}
    for table in tables2:
        for record in table.records:
            cod = record.values.get("cod_provincia")
            nom = record.values.get("provincia")
            ccaa = record.values.get("comunidad")
            if not cod or not nom:
                continue
            seen[cod] = {"id": cod, "nombre": nom, "comunidad": ccaa}
    return sorted(seen.values(), key=lambda r: r["nombre"])


@app.get("/api/municipios")
def list_municipios(
    provincia: Optional[str] = Query(None, min_length=2, max_length=2),
    comunidad: Optional[str] = None,
    q: Optional[str] = Query(None, description="Búsqueda por prefijo del nombre"),
    limit: int = Query(8000, ge=1, le=20000),
) -> list[dict]:
    rows = _municipios(provincia, comunidad)
    if q:
        q_norm = q.strip().lower()
        if q_norm:
            rows = [r for r in rows if q_norm in r["nombre"].lower()]
    return rows[:limit]


@lru_cache(maxsize=8)
def _municipios(provincia: Optional[str] = None,
                comunidad: Optional[str] = None) -> list[dict]:
    extras: list[str] = []
    params: dict = {"bucket": INFLUX_BUCKET}
    if provincia:
        extras.append("r.cod_provincia == ${prov}")
        params["prov"] = provincia
    elif comunidad:
        extras.append("r.comunidad == ${ccaa}")
        params["ccaa"] = comunidad
    extra = (" and " + " and ".join(extras)) if extras else ""

    flux = f'''
    from(bucket: ${{bucket}})
      |> range(start: -30y)
      |> filter(fn: (r) => r._measurement == "ine_stats"
                       and r.subgrupo == "municipios"
                       and r._field == "valor"
                       {extra})
      |> group(columns: ["cod_municipio", "municipio", "cod_provincia", "provincia", "comunidad"])
      |> first()
    '''
    tables = query(flux, params)
    seen: dict[str, dict] = {}
    for table in tables:
        for record in table.records:
            cod = record.values.get("cod_municipio")
            nom = record.values.get("municipio")
            if not cod or not nom:
                continue
            seen[cod] = {
                "id": cod,
                "nombre": nom,
                "cod_provincia": record.values.get("cod_provincia"),
                "provincia": record.values.get("provincia"),
                "comunidad": record.values.get("comunidad"),
            }
    return sorted(seen.values(), key=lambda r: r["nombre"])


def _scope_filter(comunidad, provincia, municipio):
    extras = []
    params = {}
    if municipio:
        extras.append("r.cod_municipio == ${muni}")
        params["muni"] = municipio
    elif provincia:
        extras.append("r.cod_provincia == ${prov}")
        params["prov"] = provincia
    elif comunidad:
        extras.append("r.comunidad == ${ccaa}")
        params["ccaa"] = comunidad
    extra = (" and " + " and ".join(extras)) if extras else ""
    return extra, params


# =================================================================
@app.get("/api/mapa")
def map_values(
    anio: int = Query(..., ge=1996, le=2100),
    sexo: str = Query("total"),
    comunidad: Optional[str] = None,
    provincia: Optional[str] = None,
    municipio: Optional[str] = None,
) -> list[dict]:
    sexo_tag = SEXO_MAP.get(sexo, "Total")
    extra, params = _scope_filter(comunidad, provincia, municipio)
    params.update({
        "bucket": INFLUX_BUCKET,
        "sexo":   sexo_tag,
        "y1":     f"{anio}-12-31T23:59:59Z",
    })
    flux = f'''
    from(bucket: ${{bucket}})
      |> range(start: 1990-01-01T00:00:00Z, stop: time(v: ${{y1}}))
      |> filter(fn: (r) => r._measurement == "ine_stats"
                       and r.subgrupo == "municipios"
                       and r._field == "valor"
                       and r.sexo == ${{sexo}}
                       {extra})
      |> group(columns: ["cod_municipio"])
      |> last()
    '''
    result = []
    for table in query(flux, params):
        for record in table.records:
            code = record.values.get("cod_municipio")
            val  = record.get_value()
            if code is not None and val is not None:
                result.append({"id": code, "valor": val})
    return result


@app.get("/api/serie")
def serie_temporal(
    comunidad: Optional[str] = None,
    provincia: Optional[str] = None,
    municipio: Optional[str] = None,
) -> dict:
    extra, params = _scope_filter(comunidad, provincia, municipio)
    params.update({"bucket": INFLUX_BUCKET})
    flux = f'''
    from(bucket: ${{bucket}})
      |> range(start: 1995-01-01T00:00:00Z, stop: 2100-01-01T00:00:00Z)
      |> filter(fn: (r) => r._measurement == "ine_stats"
                       and r.subgrupo == "municipios"
                       and r._field == "valor"
                       {extra})
      |> keep(columns: ["_time", "sexo", "_value"])
      |> group(columns: ["_time", "sexo"])
      |> sum()
    '''
    acc: dict[int, dict[str, float]] = {}
    for table in query(flux, params):
        for record in table.records:
            t = record.values.get("_time")
            if t is None:
                continue
            year = t.year
            sexo = (record.values.get("sexo") or "").lower()
            val = record.get_value() or 0
            acc.setdefault(year, {"total": 0, "hombres": 0, "mujeres": 0})
            if sexo in acc[year]:
                acc[year][sexo] += float(val)
    years = sorted(acc.keys())
    return {
        "anios":   years,
        "total":   [acc[y]["total"]   for y in years],
        "hombres": [acc[y]["hombres"] for y in years],
        "mujeres": [acc[y]["mujeres"] for y in years],
    }


@app.get("/api/ranking")
def ranking(
    anio: int = Query(..., ge=1996, le=2100),
    sexo: str = Query("total"),
    comunidad: Optional[str] = None,
    provincia: Optional[str] = None,
    municipio: Optional[str] = None,
) -> list[dict]:
    sexo_tag = SEXO_MAP.get(sexo, "Total")
    extra, params = _scope_filter(comunidad, provincia, municipio)
    params.update({
        "bucket": INFLUX_BUCKET,
        "sexo": sexo_tag,
        "y1_now":  f"{anio}-12-31T23:59:59Z",
        "y1_prev": f"{anio-1}-12-31T23:59:59Z",
    })
    flux_now = f'''
    from(bucket: ${{bucket}})
      |> range(start: 1990-01-01T00:00:00Z, stop: time(v: ${{y1_now}}))
      |> filter(fn: (r) => r._measurement == "ine_stats"
                       and r.subgrupo == "municipios"
                       and r._field == "valor"
                       and r.sexo == ${{sexo}}
                       {extra})
      |> group(columns: ["cod_municipio", "municipio", "cod_provincia"])
      |> last()
    '''
    flux_prev = f'''
    from(bucket: ${{bucket}})
      |> range(start: 1990-01-01T00:00:00Z, stop: time(v: ${{y1_prev}}))
      |> filter(fn: (r) => r._measurement == "ine_stats"
                       and r.subgrupo == "municipios"
                       and r._field == "valor"
                       and r.sexo == ${{sexo}}
                       {extra})
      |> group(columns: ["cod_municipio"])
      |> last()
    '''
    prev_map: dict[str, float] = {}
    for table in query(flux_prev, params):
        for r in table.records:
            cod = r.values.get("cod_municipio")
            if cod is not None and r.get_value() is not None:
                prev_map[cod] = float(r.get_value())

    rows = []
    for table in query(flux_now, params):
        for r in table.records:
            cod = r.values.get("cod_municipio")
            val = r.get_value()
            if cod is None or val is None:
                continue
            rows.append({
                "cod_municipio": cod,
                "nombre":        r.values.get("municipio"),
                "cod_provincia": r.values.get("cod_provincia"),
                "valor":         float(val),
                "prev":          prev_map.get(cod),
            })
    return rows


@app.get("/api/stats")
def stats(
    anio: int = Query(..., ge=1996, le=2100),
    comunidad: Optional[str] = None,
    provincia: Optional[str] = None,
    municipio: Optional[str] = None,
) -> dict:
    extra, params = _scope_filter(comunidad, provincia, municipio)
    params.update({
        "bucket": INFLUX_BUCKET,
        "y1":  f"{anio}-12-31T23:59:59Z",
        "y1p": f"{anio-1}-12-31T23:59:59Z",
    })
    flux_now = f'''
    from(bucket: ${{bucket}})
      |> range(start: 1990-01-01T00:00:00Z, stop: time(v: ${{y1}}))
      |> filter(fn: (r) => r._measurement == "ine_stats"
                       and r.subgrupo == "municipios"
                       and r._field == "valor"
                       {extra})
      |> keep(columns: ["cod_municipio", "sexo", "_value"])
      |> group(columns: ["cod_municipio", "sexo"])
      |> last()
    '''
    flux_prev = f'''
    from(bucket: ${{bucket}})
      |> range(start: 1990-01-01T00:00:00Z, stop: time(v: ${{y1p}}))
      |> filter(fn: (r) => r._measurement == "ine_stats"
                       and r.subgrupo == "municipios"
                       and r._field == "valor"
                       and r.sexo == "Total"
                       {extra})
      |> keep(columns: ["cod_municipio", "_value"])
      |> group(columns: ["cod_municipio"])
      |> last()
    '''
    total = hombres = mujeres = 0.0
    municipios: set[str] = set()
    total_by_muni: dict[str, float] = {}
    for table in query(flux_now, params):
        for r in table.records:
            v = r.get_value() or 0
            sexo = (r.values.get("sexo") or "").lower()
            cod = r.values.get("cod_municipio")
            if cod:
                municipios.add(cod)
            vf = float(v)
            if sexo == "total":
                total += vf
                if cod:
                    total_by_muni[cod] = vf
            elif sexo == "hombres":
                hombres += vf
            elif sexo == "mujeres":
                mujeres += vf

    prev_total = 0.0
    prev_by_muni: dict[str, float] = {}
    for table in query(flux_prev, params):
        for r in table.records:
            cod = r.values.get("cod_municipio")
            v = float(r.get_value() or 0)
            prev_total += v
            if cod:
                prev_by_muni[cod] = v

    delta = total - prev_total
    delta_pct = (delta / prev_total * 100) if prev_total else None
    masc = (hombres / mujeres * 100) if mujeres else None

    municipios_regresion = 0
    municipios_comparables = 0
    for cod, v_now in total_by_muni.items():
        v_prev = prev_by_muni.get(cod)
        if v_prev is None or v_prev <= 0:
            continue
        municipios_comparables += 1
        if v_now < v_prev:
            municipios_regresion += 1
    regresion_pct = (
        municipios_regresion / municipios_comparables * 100
        if municipios_comparables else None
    )
    return {
        "anio":             anio,
        "poblacion_total":  total,
        "hombres":          hombres,
        "mujeres":          mujeres,
        "prev_total":       prev_total,
        "delta":            delta,
        "delta_pct":        delta_pct,
        "indice_masc":      masc,
        "num_municipios":   len(municipios),
        "municipios_regresion":   municipios_regresion,
        "municipios_comparables": municipios_comparables,
        "regresion_pct":          regresion_pct,
    }


# =================================================================
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


def _canon_sector(nombre: str) -> Optional[str]:
    n = normaliza(nombre)
    if n in _SECTOR_TOTALES:
        return None
    for clave, agujas in _SECTOR_CANON:
        if any(a in n for a in agujas):
            return clave
    return "otros_servicios"


@lru_cache(maxsize=8)
def _poblacion_pesos(anio: int) -> dict:
    """Población total (sexo Total) por municipio, último valor <= año.
    Sirve de peso para las medias a nivel provincial (tasas NUNCA se suman)."""
    params = {"bucket": INFLUX_BUCKET, "stop": f"{anio}-12-31T23:59:59Z"}
    flux = '''
    from(bucket: ${bucket})
      |> range(start: 1990-01-01T00:00:00Z, stop: time(v: ${stop}))
      |> filter(fn: (r) => r._measurement == "ine_stats" and r._field == "valor"
                       and r.subgrupo == "municipios" and r.sexo == "Total")
      |> group(columns: ["cod_municipio"])
      |> last()
      |> keep(columns: ["cod_municipio", "_value"])
    '''
    pesos: dict[str, float] = {}
    for table in query(flux, params):
        for r in table.records:
            cod = r.values.get("cod_municipio")
            val = r.get_value()
            if cod and val is not None:
                pesos[cod] = float(val)
    return pesos


_CAPA_START = "2000-01-01T00:00:00Z"


@lru_cache(maxsize=8)
def _capa_renta_prov(anio: int) -> dict:
    """Renta bruta media por persona (€) por PROVINCIA, último valor <= año.
    Esta serie del INE es provincial (no municipal): la geografía es la
    provincia, así que agrupamos por cod_provincia."""
    params = {"bucket": INFLUX_BUCKET, "start": _CAPA_START,
              "stop": f"{anio}-12-31T23:59:59Z"}
    flux = '''
    from(bucket: ${bucket})
      |> range(start: time(v: ${start}), stop: time(v: ${stop}))
      |> filter(fn: (r) => r._measurement == "ine_stats"
                       and r._field == "valor"
                       and r.subgrupo == "renta")
      |> group(columns: ["cod_provincia"])
      |> last()
      |> keep(columns: ["cod_provincia", "_value"])
    '''
    out: dict[str, float] = {}
    for table in query(flux, params):
        for r in table.records:
            cod = r.values.get("cod_provincia")
            val = r.get_value()
            if cod and val is not None:
                out[cod] = float(val)
    return out


@lru_cache(maxsize=8)
def _capa_trabajo_muni(anio: int) -> tuple[dict, ...]:
    params = {"bucket": INFLUX_BUCKET, "start": _CAPA_START,
              "stop": f"{anio}-12-31T23:59:59Z"}
    flux = '''
    from(bucket: ${bucket})
      |> range(start: time(v: ${start}), stop: time(v: ${stop}))
      |> filter(fn: (r) => r._measurement == "ine_stats"
                       and r._field == "valor"
                       and r.subgrupo == "trabajo")
      |> group(columns: ["cod_municipio", "sector"])
      |> last()
      |> keep(columns: ["cod_municipio", "sector", "_value"])
    '''
    por_muni: dict[str, dict[str, float]] = {}
    total_muni: dict[str, float] = {}
    for table in query(flux, params):
        for r in table.records:
            cod = r.values.get("cod_municipio")
            sector_raw = r.values.get("sector") or ""
            val = r.get_value()
            if not cod or val is None:
                continue
            if normaliza(sector_raw) == "total":
                total_muni[cod] = float(val)
                continue
            clave = _canon_sector(sector_raw)
            if clave is None:
                continue
            por_muni.setdefault(cod, {})
            por_muni[cod][clave] = por_muni[cod].get(clave, 0.0) + float(val)

    out = []
    for cod, sectores in por_muni.items():
        if not sectores:
            continue
        dom = max(sectores.items(), key=lambda kv: kv[1])
        out.append({"id": cod, "sector": dom[0], "valor": dom[1],
                    "total": total_muni.get(cod)})
    return tuple(out)


@lru_cache(maxsize=8)
def _capa_estudios_muni(anio: int) -> tuple[dict, ...]:
    params = {"bucket": INFLUX_BUCKET, "start": _CAPA_START,
              "stop": f"{anio}-12-31T23:59:59Z"}
    flux = '''
    from(bucket: ${bucket})
      |> range(start: time(v: ${start}), stop: time(v: ${stop}))
      |> filter(fn: (r) => r._measurement == "ine_stats"
                       and r._field == "valor"
                       and r.subgrupo == "estudios"
                       and r.sexo == "Total")
      |> group(columns: ["cod_municipio", "nivel_estudio", "grupo_edad"])
      |> last()
      |> keep(columns: ["cod_municipio", "nivel_estudio", "grupo_edad", "_value"])
    '''
    bruto: dict[str, dict[str, dict[str, float]]] = {}
    for table in query(flux, params):
        for r in table.records:
            cod = r.values.get("cod_municipio")
            nivel = r.values.get("nivel_estudio") or ""
            edad = r.values.get("grupo_edad") or "todas"
            val = r.get_value()
            if not cod or val is None:
                continue
            bruto.setdefault(cod, {}).setdefault(edad, {})
            bruto[cod][edad][normaliza(nivel)] = float(val)

    out = []
    for cod, por_edad in bruto.items():
        edad_agg = None
        for edad in por_edad:
            if normaliza(edad) in ("total", "todas", "todos"):
                edad_agg = edad
                break
        if edad_agg is None:
            edad_agg = max(por_edad, key=lambda e: sum(por_edad[e].values()))
        niveles = por_edad[edad_agg]
        denom = next((v for k, v in niveles.items() if "total" in k), None)
        if denom is None:
            denom = sum(niveles.values())
        if not denom:
            continue
        superior = sum(v for k, v in niveles.items() if "superior" in k)
        out.append({"id": cod, "valor": round(superior / denom * 100, 1)})
    return tuple(out)


def _agg_provincia(modo: str, rows: list[dict], pesos: dict) -> list[dict]:
    if modo == "trabajo":
        prov_sect: dict[str, dict[str, float]] = {}
        prov_total: dict[str, float] = {}
        for r in rows:
            prov = r["id"][:2]
            prov_sect.setdefault(prov, {})
            prov_sect[prov][r["sector"]] = prov_sect[prov].get(r["sector"], 0.0) + r["valor"]
            if r.get("total"):
                prov_total[prov] = prov_total.get(prov, 0.0) + r["total"]
        out = []
        for prov, sect in prov_sect.items():
            dom = max(sect.items(), key=lambda kv: kv[1])
            out.append({"id": prov, "sector": dom[0], "valor": dom[1],
                        "total": prov_total.get(prov)})
        return out

    num: dict[str, float] = {}
    den: dict[str, float] = {}
    for r in rows:
        prov = r["id"][:2]
        w = pesos.get(r["id"], 0.0) or 1.0  
        num[prov] = num.get(prov, 0.0) + r["valor"] * w
        den[prov] = den.get(prov, 0.0) + w
    return [{"id": p, "valor": round(num[p] / den[p], 1)} for p in num if den[p] > 0]


_CAPAS_MUNI = {
    "trabajo":  _capa_trabajo_muni,
    "estudios": _capa_estudios_muni,
}

_capa_cache: dict[tuple, list[dict]] = {}


@app.get("/api/capa/{modo}")
def capa_tematica(
    modo: str,
    anio: int = Query(DEFAULT_ANIO, ge=1996, le=2100),
    nivel: str = Query("municipio"),
    provincia: Optional[str] = Query(None, min_length=2, max_length=2),
) -> list[dict]:
    if modo not in ("renta", "trabajo", "estudios"):
        raise HTTPException(status_code=404, detail=f"Modo de capa desconocido: {modo}")

    nivel = "provincia" if nivel == "provincia" else "municipio"
    key = (modo, anio, nivel)
    rows = _capa_cache.get(key)
    if rows is None:
        if modo == "renta":
            prov_vals = _capa_renta_prov(anio)
            if nivel == "provincia":
                rows = [{"id": p, "valor": v} for p, v in prov_vals.items()]
            else:
                muni_cods = _poblacion_pesos(anio).keys()
                rows = [{"id": cod, "valor": prov_vals[cod[:2]]}
                        for cod in muni_cods if cod[:2] in prov_vals]
        else:
            muni = _CAPAS_MUNI[modo](anio)
            rows = _agg_provincia(modo, muni, _poblacion_pesos(anio)) if nivel == "provincia" else muni
        _capa_cache[key] = rows

    if nivel == "municipio" and provincia:
        rows = [r for r in rows if r["id"][:2] == provincia]
    return rows


# =================================================================
#  Chat con Ollama de prueba
# =================================================================
INDICADOR_CFG: dict[str, dict] = {
    "municipios":     {"subgrupo": "municipios",     "agg": "sum",  "sexo": "Total",        "label": "población",          "unidad": ""},
    "renta":          {"subgrupo": "renta",          "agg": "mean", "sexo": None,           "label": "renta media",        "unidad": "€"},
    "esperanza_vida": {"subgrupo": "esperanza_vida", "agg": "mean", "sexo": "Ambos sexos",  "label": "esperanza de vida",  "unidad": "años"},
    "edad_mediana":   {"subgrupo": "edad_mediana",   "agg": "mean", "sexo": "Ambos sexos",  "label": "edad mediana",       "unidad": "años"},
    "fecundidad":     {"subgrupo": "fecundidad",     "agg": "mean", "sexo": None,           "label": "indicador de fecundidad", "unidad": ""},
}

GENERICOS = {"provincia", "provincias", "municipio", "municipios",
             "comunidad", "comunidades", "espana", "pais", "lugar", "sitio"}


def query_filas(flux: str, params: dict) -> list:
    try:
        return [dict(r.values) for t in query(flux, params) for r in t.records]
    except HTTPException as exc:
        if "_value" in str(exc.detail):
            return []
        raise


def ollama(messages: list, fmt: Optional[str] = None,
            temperature: float = 0.0, num_ctx: int = 4096) -> str:
    body = {"model": OLLAMA_MODEL, "messages": messages, "stream": False,
            "options": {"temperature": temperature, "num_ctx": num_ctx}}
    if fmt:
        body["format"] = fmt
    with httpx.Client(timeout=OLLAMA_TIMEOUT) as cli:
        r = cli.post(f"{OLLAMA_URL}/api/chat", json=body)
        r.raise_for_status()
        return r.json()["message"]["content"].strip()


def normaliza(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").strip()


def resolver_lugar(nombre: str) -> Optional[dict]:
    if not nombre:
        return None
    objetivo = normaliza(nombre)

    provincias = _provincias()
    idx_prov = {normaliza(p["nombre"]): p for p in provincias}
    m = get_close_matches(objetivo, list(idx_prov.keys()), n=1, cutoff=0.82)
    if m:
        p = idx_prov[m[0]]
        return {"nivel": "provincia", "cod": p["id"], "nombre": p["nombre"]}

    municipios = _municipios()
    idx_mun = {normaliza(mu["nombre"]): mu for mu in municipios}
    m = get_close_matches(objetivo, list(idx_mun.keys()), n=1, cutoff=0.82)
    if m:
        mu = idx_mun[m[0]]
        return {"nivel": "municipio", "cod": mu["id"], "nombre": mu["nombre"]}

    return None


def build_flux(cfg: dict, *, anio: Optional[int] = None,
               rango: Optional[tuple] = None, lugar: Optional[dict] = None,
               modo: str = "valor", orden: str = "desc") -> tuple[str, dict]:
    params: dict = {"bucket": INFLUX_BUCKET, "subgrupo": cfg["subgrupo"]}

    if rango:
        rng = f"start: {rango[0]}-01-01T00:00:00Z, stop: {rango[1]}-12-31T23:59:59Z"
    elif anio:
        rng = f"start: {anio}-01-01T00:00:00Z, stop: {anio}-12-31T23:59:59Z"
    else:
        rng = "start: 1995-01-01T00:00:00Z"

    sexo = ""
    if cfg["sexo"]:
        sexo = "and r.sexo == ${sexo}"
        params["sexo"] = cfg["sexo"]

    scope = ""
    if lugar:
        col = "cod_municipio" if lugar["nivel"] == "municipio" else "cod_provincia"
        scope = f"and r.{col} == ${{cod}}"
        params["cod"] = lugar["cod"]

    agg = "sum" if cfg["agg"] == "sum" else "mean"
    base = (f"from(bucket: ${{bucket}}) |> range({rng}) "
            f'|> filter(fn: (r) => r._measurement == "ine_stats" '
            f'and r._field == "valor" and r.subgrupo == ${{subgrupo}} '
            f"{sexo} {scope})")

    if modo == "ranking":
        desc = "true" if orden == "desc" else "false"
        # si hay una provincia acotada -> ranking de municipios dentro de ella;
        # si no -> ranking de provincias
        col_group = "municipio" if (lugar and lugar["nivel"] == "provincia") else "provincia"
        flux_q = (base + f' |> group(columns:["{col_group}"]) |> {agg}() |> group() '
                         f'|> sort(columns:["_value"], desc:{desc}) |> limit(n:50)')
    elif modo == "serie":
        flux_q = (base + f' |> group(columns:["provincia","_time"]) |> {agg}() '
                         f'|> group(columns:["provincia"]) |> sort(columns:["_time"])')
    else:
        flux_q = base + ' |> keep(columns:["_value","_time","municipio","provincia"])'
    return flux_q, params


def contexto(msg: str) -> dict:
    system = (
        "Analiza una pregunta demográfica del INE de España. "
        "Corrige faltas de ortografía. Devuelve SOLO un JSON válido, sin markdown:\n"
        '{"influx":"<Si|No>","lugar":"<nombre|null>","anio":<año|null>,'
        '"subgrupo":"<municipios|edad_mediana|migracion|fecundidad|natalidad|mortalidad|esperanza_vida|trabajo|estudios|estadoCivil|renta>",'
        '"ranking":<true|false>,"orden":"<desc|asc>","limite":<n|null>}\n'
        "influx=Si SIEMPRE que la pregunta pida cualquier dato demográfico (población, "
        "habitantes, renta, edad, nacimientos, etc.) de un lugar, un ranking o una evolución. "
        "Ejemplos influx=Si: 'población de Valladolid', 'renta de Soria', "
        "'las 5 provincias con más habitantes', 'cuántos nacimientos hubo en 2020'.\n"
        "influx=No SOLO para saludos ('hola'), agradecimientos o preguntas sobre cómo "
        "usar la app. Ejemplos influx=No: 'hola', 'qué puedes hacer', 'gracias'.\n"
        "Ante la duda, influx=Si.\n"
        "lugar: el municipio, provincia o comunidad CONCRETO mencionado por su nombre propio "
        "(ej: 'Valladolid', 'Soria'). Si es un ranking general sin lugar concreto "
        "(ej: 'las 5 provincias con más población'), lugar=null. "
        "Nunca uses palabras genéricas como 'provincia' o 'municipio' como lugar.\n"
        "anio: año mencionado como número; null si no se menciona.\n"
        "ranking=true si pide ordenar o el/los que más o menos tienen, INCLUSO si pide solo uno "
        "(ej: 'la provincia con más población' -> ranking=true, limite=1; "
        "'los 5 municipios más poblados' -> ranking=true, limite=5). "
        "ranking=false si pide la cifra de un lugar concreto.\n"
        "orden=asc para menos/menor/más bajo; desc para más/mayor.\n"
        "limite: número de elementos pedidos. Si pide UNO o usa singular "
        "('la provincia con mayor población', 'el municipio más poblado', "
        "'cuál tiene más habitantes'), limite=1. 'las 5' -> 5. Plural sin cantidad -> null.\n"
        "subgrupo: clasifica la pregunta en el tema al que pertenece:\n"
        "- municipios: población, habitantes, censo.\n"
        "- edad_mediana: edad media/mediana, envejecimiento.\n"
        "- migracion: inmigración, emigración, extranjeros.\n"
        "- fecundidad: hijos por mujer.\n"
        "- natalidad: nacimientos.\n"
        "- mortalidad: defunciones.\n"
        "- esperanza_vida: esperanza de vida, longevidad.\n"
        "- trabajo: empleo, paro, ocupación.\n"
        "- estudios: nivel educativo, formación.\n"
        "- estadoCivil: solteros, casados, viudos, divorciados.\n"
        "- renta: renta media, ingresos.\n"
        "Si no se menciona tema, usa municipios."
    )
    raw = ollama(
        [{"role": "system", "content": system},
         {"role": "user", "content": f"Pregunta: {msg}"}], fmt="json")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("JSON inválido del LLM: %s", raw)
        return {"influx": "No", "lugar": None, "anio": None,
                "subgrupo": "municipios", "ranking": False, "orden": "desc", "limite": None}


def redactar(msg: str, cfg: dict, filas: list, historial: list, modo: str) -> str:
    if modo == "conversacion":
        system = (
            "Eres un asistente de datos demográficos del INE de España. "
            "Responde con cordialidad y en el idioma en que te preguntan.\n"
            "Contesta lo más resumido posible, ya que es un mensaje de chat, "
            "salvo que la pregunta requiera algo más de texto.\n"
            "No respondas con cifras: para eso habría que consultar la base de datos. "
            "Si no sabes cómo resolver algo, di que aún no sabes responder a eso.\n"
        )
        user = f"Pregunta: {msg}\n"
        mensajes = [{"role": "system", "content": system}]
        mensajes.extend(historial[-6:])
        mensajes.append({"role": "user", "content": user})
    else:
        system = (
            "Eres un asistente de datos demográficos del INE de España. "
            "Reglas estrictas:\n"
            "1. Responde SOLO con los datos que te paso en 'Datos'. Está "
            "TERMINANTEMENTE PROHIBIDO inventar o estimar cifras, lugares o años. "
            "Si un dato no está en 'Datos', di que no lo tienes.\n"
            "2. No uses conocimiento previo tuyo sobre poblaciones: usa únicamente "
            "las cifras de 'Datos'.\n"
            "3. Formato: empieza con una frase directa que responda la pregunta. "
            "Si hay varias cifras (ranking o serie), usa una lista con guiones, "
            "una línea por elemento, con su valor. Sé conciso.\n"
            "4. Responde en el idioma que te hablan.\n"
            "5. Si la respuesta tiene cifras, ponlas en formato numérico.\n"
            "6. Escribe completo pero resumido: al fin y al cabo es un mensaje de chat.\n"
        )
        user = (f"Pregunta: {msg}\n"
                f"Indicador: {cfg['label']} (unidad: '{cfg['unidad'] or 'personas'}')\n"
                f"Datos (JSON, son los ÚNICOS válidos): "
                f"{json.dumps(filas, ensure_ascii=False, default=str)}")
        mensajes = [{"role": "system", "content": system}]
        mensajes.extend(historial[-6:])
        mensajes.append({"role": "user", "content": user})
    return ollama(mensajes)


@app.post("/api/chat")
def chat(payload: dict = Body(...)) -> dict:
    payload = payload or {}
    msg = (payload.get("message") or "").strip()
    historial = [m for m in (payload.get("messages") or [])
                 if isinstance(m, dict) and m.get("role") in ("user", "assistant")]

    try:
        context = contexto(msg)
        logger.debug("contexto extraído: %s", context)
    except Exception:
        logger.exception("contexto")
        return {"text": "No he podido interpretar la pregunta. Reformúlala, por favor."}

    # ¿necesita datos? -> hay lugar concreto o es un ranking
    tiene_lugar = bool(context.get("lugar"))
    es_ranking = context.get("ranking") is True
    influx_si = str(context.get("influx", "")).strip().lower() in ("si", "sí", "yes", "true")
    # red de seguridad: si dijo No pero hay lugar/ranking, es pregunta de datos
    necesita_datos = influx_si or tiene_lugar or es_ranking

    if not necesita_datos:
        return {"text": redactar(msg, {}, [], historial, "conversacion")}

    # indicador (protegido por si el LLM devuelve uno no cargado)
    sub = context.get("subgrupo") or "municipios"
    cfg = INDICADOR_CFG.get(sub)
    if cfg is None:
        return {"text": f"Todavía no tengo datos de «{sub}». "
                        "Puedo consultar población, renta, esperanza de vida, "
                        "edad mediana y fecundidad."}

    # resolver lugar (puede ser None: ranking nacional o total España)
    lugar_str = context.get("lugar")
    lugar = None
    if lugar_str and normaliza(lugar_str) not in GENERICOS:
        lugar = resolver_lugar(lugar_str)
        if lugar is None:
            return {"text": f"No encuentro ningún lugar llamado «{lugar_str}». "
                            "Revisa el nombre."}

    anio = context.get("anio")
    try:
        anio = int(anio) if anio is not None else DEFAULT_ANIO
    except (ValueError, TypeError):
        anio = DEFAULT_ANIO

    lugar_nombre = lugar["nombre"] if lugar else None

    # construcción de la query
    try:
        if es_ranking:
            flux_q, params = build_flux(cfg, anio=anio, lugar=lugar,
                                        modo="ranking", orden=context.get("orden", "desc"))
        else:
            flux_q, params = build_flux(cfg, anio=anio, lugar=lugar, modo="valor")
        filas = query_filas(flux_q, params)
    except Exception:
        logger.exception("query")
        return {"text": "Hubo un problema consultando los datos. Inténtalo de nuevo."}

    # nunca redactar con datos vacíos
    if not filas:
        donde = f" para {lugar_nombre}" if lugar_nombre else ""
        return {"text": f"No tengo datos de {cfg['label']}{donde} en {anio}. "
                        "Prueba con otro año, indicador o lugar.",
                "lugar": lugar_nombre}

    unidad = cfg["unidad"] or "habitantes"
    es_entero = cfg["agg"] == "sum"

    def fmt(v: float) -> str:
        if es_entero:
            return f"{round(v):,}".replace(",", ".")
        return f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")

    if es_ranking:
        # límite: respeta el del LLM; si no hay, deduce singular vs plural
        limite = context.get("limite")
        if limite is None:
            msg_norm = normaliza(msg)
            singular = any(p in msg_norm for p in (
                "la provincia", "el municipio", "la comunidad",
                "cual tiene", "cual es la", "cual es el",
                "que provincia", "que municipio", "mayor poblacion", "menor poblacion"))
            limite = 1 if singular else 10

        items = [{"lugar": f.get("municipio") or f.get("provincia"),
                  "valor": float(f["_value"])}
                 for f in filas if f.get("_value") is not None][:limite]
        if not items:
            return {"text": f"No tengo datos de {cfg['label']} para esa consulta.",
                    "lugar": None}

        nivel = "municipio" if (lugar and lugar["nivel"] == "provincia") else "provincia"

        # caso "la provincia/municipio con mayor X" (un solo resultado)
        if limite == 1:
            it = items[0]
            comp = "mayor" if context.get("orden", "desc") == "desc" else "menor"
            articulo = "El" if nivel == "municipio" else "La"
            return {"text": f"{articulo} {nivel} con {comp} {cfg['label']} es {it['lugar']}, "
                            f"con {fmt(it['valor'])} {unidad}.",
                    "lugar": it["lugar"]}

        # ranking de varios
        lineas = "\n".join(f"- {it['lugar']}: {fmt(it['valor'])} {unidad}" for it in items)
        encabezado = f"Ranking de {cfg['label']}"
        if lugar:
            encabezado += f" en {lugar['nombre']}"
        return {"text": f"{encabezado}:\n{lineas}", "lugar": lugar_nombre}

    # valor único: agrega en Python y redacta con el LLM (una sola cifra, riesgo bajo)
    valores = [float(f["_value"]) for f in filas if f.get("_value") is not None]
    if not valores:
        return {"text": f"No tengo datos de {cfg['label']} para esa consulta.",
                "lugar": lugar_nombre}
    total = sum(valores) if cfg["agg"] == "sum" else sum(valores) / len(valores)
    filas = [{"lugar": lugar_nombre or "España", "anio": anio,
              "valor": round(total, 1), "unidad": cfg["unidad"] or "personas"}]

    return {"text": redactar(msg, cfg, filas, historial, "valor"),
            "lugar": lugar_nombre}