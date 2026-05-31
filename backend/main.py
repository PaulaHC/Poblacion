import logging
import os
import re
from functools import lru_cache
from typing import Any, Optional

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from influxdb_client import InfluxDBClient

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("poview.backend")

INFLUX_URL    = os.environ.get("INFLUXDB_URL",    "http://influxdb:8086")
INFLUX_TOKEN  = os.environ.get("INFLUXDB_TOKEN",  "")
INFLUX_ORG    = os.environ.get("INFLUXDB_ORG",    "tfm_rural")
INFLUX_BUCKET = os.environ.get("INFLUXDB_BUCKET", "poblacion_municipios")
CORS_ORIGINS  = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",")]

SEXO_MAP = {"total": "Total", "hombres": "Hombres", "mujeres": "Mujeres"}


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
        if isinstance(v, str):
            return f'"{_escape_flux_string(v)}"'
        if isinstance(v, bool):
            return "true" if v else "false"
        return str(v)
    return _PLACEHOLDER.sub(repl, flux)


def query(flux: str, params: Optional[dict] = None):
    rendered = _render_flux(flux, params or {})
    try:
        return get_client().query_api().query(rendered)
    except Exception as exc:
        logger.exception("Influx query falló")
        raise HTTPException(
            status_code=502, detail=f"Influx error: {exc}"
        ) from exc


app = FastAPI(title="Poview backend", version="0.8.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    try:
        get_client().ping()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------
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


# ---------------------------------------------------------------
@app.get("/api/provincias")
def list_provincias(comunidad: Optional[str] = None) -> list[dict]:
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


# ---------------------------------------------------------------
#  /api/municipios
#
#  Acepta CUALQUIERA de los tres ámbitos (comunidad / provincia / sin ámbito):
#    - provincia: devuelve municipios de esa provincia (caso ya soportado).
#    - comunidad sin provincia: devuelve municipios de toda la comunidad.
#    - sin ámbito: devuelve TODOS los municipios de España.
#
#  Cada municipio incluye cod_provincia, provincia y comunidad, para que
#  el frontend pueda autocompletar los selects superiores cuando el usuario
#  elige un municipio "suelto" (sin haber filtrado provincia antes).
# ---------------------------------------------------------------
@app.get("/api/municipios")
def list_municipios(
    provincia: Optional[str] = Query(None, min_length=2, max_length=2),
    comunidad: Optional[str] = None,
    q: Optional[str] = Query(None, description="Búsqueda por prefijo del nombre"),
    limit: int = Query(8000, ge=1, le=20000),
) -> list[dict]:
    # Construir el filtro según el ámbito recibido
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

    # Normalización del término de búsqueda
    q_norm: Optional[str] = None
    if q:
        q_norm = q.strip().lower()
        if not q_norm:
            q_norm = None

    seen: dict[str, dict] = {}
    for table in tables:
        for record in table.records:
            cod = record.values.get("cod_municipio")
            nom = record.values.get("municipio")
            cprov = record.values.get("cod_provincia")
            prov = record.values.get("provincia")
            ccaa = record.values.get("comunidad")
            if not cod or not nom:
                continue
            if q_norm and q_norm not in nom.lower():
                continue
            seen[cod] = {
                "id": cod,
                "nombre": nom,
                "cod_provincia": cprov,
                "provincia": prov,
                "comunidad": ccaa,
            }
    rows = sorted(seen.values(), key=lambda r: r["nombre"])
    return rows[:limit]


def _scope_filter(comunidad, provincia, municipio):
    """Filtro Flux para acotar por ámbito.

    Si llega `municipio` lo usamos solo (es identificador único). Antes se
    descartaban comunidad/provincia cuando había provincia, pero municipio
    se trataba igual sin requerir provincia (era el comportamiento deseado).
    """
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


# ---------------------------------------------------------------
#  /api/mapa
#
#  Devuelve por MUNICIPIO (cod_municipio == cod_ine).
#  Si se filtra por municipio concreto, devuelve solo ese.
# ---------------------------------------------------------------
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
        "y0":     f"{anio}-01-01T00:00:00Z",
        "y1":     f"{anio}-12-31T23:59:59Z",
    })

    flux = f'''
    from(bucket: ${{bucket}})
      |> range(start: time(v: ${{y0}}), stop: time(v: ${{y1}}))
      |> filter(fn: (r) => r._measurement == "ine_stats"
                       and r.subgrupo == "municipios"
                       and r._field == "valor"
                       and r.sexo == ${{sexo}}
                       {extra})
      |> group(columns: ["cod_municipio"])
      |> last()
    '''

    tables = query(flux, params)
    result = []
    for table in tables:
        for record in table.records:
            code = record.values.get("cod_municipio")
            val  = record.get_value()
            if code is not None and val is not None:
                result.append({"id": code, "valor": val})
    return result


# ---------------------------------------------------------------
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
    tables = query(flux, params)

    acc: dict[int, dict[str, float]] = {}
    for table in tables:
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


# ---------------------------------------------------------------
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
        "y0_now":  f"{anio}-01-01T00:00:00Z",
        "y1_now":  f"{anio}-12-31T23:59:59Z",
        "y0_prev": f"{anio-1}-01-01T00:00:00Z",
        "y1_prev": f"{anio-1}-12-31T23:59:59Z",
    })

    flux_now = f'''
    from(bucket: ${{bucket}})
      |> range(start: time(v: ${{y0_now}}), stop: time(v: ${{y1_now}}))
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
      |> range(start: time(v: ${{y0_prev}}), stop: time(v: ${{y1_prev}}))
      |> filter(fn: (r) => r._measurement == "ine_stats"
                       and r.subgrupo == "municipios"
                       and r._field == "valor"
                       and r.sexo == ${{sexo}}
                       {extra})
      |> group(columns: ["cod_municipio"])
      |> last()
    '''

    now = query(flux_now, params)
    prev = query(flux_prev, params)

    prev_map: dict[str, float] = {}
    for table in prev:
        for r in table.records:
            cod = r.values.get("cod_municipio")
            if cod is not None and r.get_value() is not None:
                prev_map[cod] = float(r.get_value())

    rows = []
    for table in now:
        for r in table.records:
            cod = r.values.get("cod_municipio")
            nom = r.values.get("municipio")
            cprov = r.values.get("cod_provincia")
            val = r.get_value()
            if cod is None or val is None:
                continue
            valf = float(val)
            pv = prev_map.get(cod)
            rows.append({
                "cod_municipio":  cod,
                "nombre":         nom,
                "cod_provincia":  cprov,
                "valor":          valf,
                "prev":           pv,
            })
    return rows


# ---------------------------------------------------------------
@app.get("/api/stats")
def stats(
    anio: int = Query(..., ge=1996, le=2100),
    comunidad: Optional[str] = None,
    provincia: Optional[str] = None,
    municipio: Optional[str] = None,
) -> dict:
    """KPIs de cabecera.

    Cambios respecto a la versión anterior:
      - Sustituye el KPI "densidad" (siempre N/D) por "municipios en regresión":
        número y porcentaje de municipios cuya población es inferior a la del
        año previo. Es un indicador directo de la "España vaciada".
    """
    extra, params = _scope_filter(comunidad, provincia, municipio)
    params.update({
        "bucket": INFLUX_BUCKET,
        "y0":  f"{anio}-01-01T00:00:00Z",
        "y1":  f"{anio}-12-31T23:59:59Z",
        "y0p": f"{anio-1}-01-01T00:00:00Z",
        "y1p": f"{anio-1}-12-31T23:59:59Z",
    })

    flux_now = f'''
    from(bucket: ${{bucket}})
      |> range(start: time(v: ${{y0}}), stop: time(v: ${{y1}}))
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
      |> range(start: time(v: ${{y0p}}), stop: time(v: ${{y1p}}))
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
    # Para "municipios en regresión" necesitamos el total por municipio del
    # año en curso, no la suma global.
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

    # Municipios en regresión: tienen valor previo y población actual < previa.
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
        # nuevos campos
        "municipios_regresion":    municipios_regresion,
        "municipios_comparables":  municipios_comparables,
        "regresion_pct":           regresion_pct,
    }


# ---------------------------------------------------------------
@app.post("/api/chat")
def chat_stub(payload: dict = Body(...)) -> dict:
    return {
        "text": (
            "El asistente todavía no está disponible en esta instancia. "
            "Usa los filtros y las vistas Gráficos / Estadísticas."
        ),
    }