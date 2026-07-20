import logging
import os
from functools import lru_cache
from typing import Optional

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from db import (
    DEFAULT_ANIO,
    INFLUX_BUCKET,
    SEXO_MAP,
    _escape_flux_string,
    _municipios,
    _provincias,
    normaliza,
    query,
)
from chat import responder_chat

logger = logging.getLogger("poview.backend")
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",")]

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
    logger.info("[capa] modo=%s nivel=%s prov=%s -> %d filas", modo, nivel, provincia, len(rows))
    return rows


# =================================================================
# Chat conversacional: delega en el agente LangGraph (ver agent.py).
# El frontend envía { "message": str, "thread_id": str }. El thread_id
# identifica la conversación para mantener memoria entre turnos.
# =================================================================
@app.post("/api/chat")
async def chat(payload: dict = Body(...)) -> dict:
    payload = payload or {}
    msg = (payload.get("message") or "").strip()
    thread_id = (payload.get("thread_id") or "default").strip() or "default"

    if not msg:
        return {"text": "Escribe una pregunta para empezar."}

    try:
        return await responder_chat(msg, thread_id)   # <-- await
    except Exception:
        logger.exception("chat")
        return {"text": "Lo siento, no he podido responder. Inténtalo de nuevo."}