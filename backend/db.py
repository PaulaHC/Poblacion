import logging
import os
import re
import time
import unicodedata
from functools import lru_cache, wraps
from typing import Any, Optional

import httpx
from fastapi import HTTPException
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

# ---- Configuración de Ollama --------------------------------------
OLLAMA_URL     = os.environ.get("OLLAMA_URL",     "http://ollama:11434")
OLLAMA_MODEL   = os.environ.get("OLLAMA_MODEL",   "qwen3:1.7b")
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "120"))

SEXO_MAP = {"total": "Total", "hombres": "Hombres", "mujeres": "Mujeres"}

DEFAULT_ANIO = int(os.environ.get("DEFAULT_ANIO", "2025"))

# TTL (segundos) de las cachés en memoria del backend. Debe ser <= a la
# cadencia del ETL (por defecto diario) para que los datos recién cargados
# acaben siendo visibles sin reiniciar el contenedor.
CACHE_TTL = int(os.environ.get("CACHE_TTL", str(24 * 3600)))


def ttl_cache(seconds: int = CACHE_TTL, maxsize: int = 8):
    """`lru_cache` con caducidad: la caché se vacía entera cada `seconds`.

    Motivo: el ETL recarga InfluxDB cada noche; sin TTL, un `lru_cache`
    normal serviría datos obsoletos hasta reiniciar el backend.
    """
    def deco(fn):
        cached = lru_cache(maxsize=maxsize)(fn)
        expira = time.monotonic() + seconds

        @wraps(fn)
        def wrapper(*args, **kwargs):
            nonlocal expira
            ahora = time.monotonic()
            if ahora >= expira:
                cached.cache_clear()
                expira = ahora + seconds
            return cached(*args, **kwargs)

        wrapper.cache_clear = cached.cache_clear
        return wrapper
    return deco


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
            logger.exception("Influx query falló | flux=%s", " ".join(rendered.split())[:800])
            raise HTTPException(status_code=502, detail=f"Influx error: {exc}") from exc


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


@ttl_cache(maxsize=8)
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


def normaliza(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").strip()


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