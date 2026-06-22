import datetime
import logging
import os
from typing import Iterable

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from influxdb_client.rest import ApiException

BATCH_SIZE = 5000
MEASUREMENT = "ine_stats"

logger = logging.getLogger(__name__)

INFLUX_URL = os.getenv("INFLUXDB_URL", "http://influxdb:8086")
INFLUX_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
INFLUX_ORG = os.getenv("INFLUXDB_ORG", "")
INFLUX_BUCKET = os.getenv("INFLUXDB_BUCKET", "")


def _parse_periodo(periodo) -> datetime.datetime | None:
    if periodo is None:
        return None
    s = str(periodo).strip()
    if not s:
        return None
    if len(s) == 4 and s.isdigit():
        s = f"{s}-01-01"
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _build_point(categoria: str, subgrupo: str, tabla: str, r: dict) -> Point | None:
    dt = _parse_periodo(r.get("periodo"))
    if dt is None:
        return None

    valor = r.get("valor")
    if valor is None:
        return None
    try:
        valor = float(valor)
    except (TypeError, ValueError):
        return None

    p = (
        Point(MEASUREMENT)
        .tag("categoria", str(categoria))
        .tag("subgrupo", str(subgrupo))
        .tag("tabla", str(tabla))
        .field("valor", valor)
        .time(dt, WritePrecision.NS)
    )

    for k, v in r.items():
        if k in ("valor", "periodo"):
            continue
        if v is None:
            v = "null"
        p = p.tag(str(k), str(v))

    return p


def emitir_metricas(categoria: str, subgrupo: str, tabla: str, registros: Iterable[dict]) -> int:

    if not INFLUX_TOKEN or not INFLUX_ORG or not INFLUX_BUCKET:
        raise RuntimeError(
            "Faltan variables de entorno INFLUXDB_TOKEN / INFLUXDB_ORG / INFLUXDB_BUCKET"
        )

    escritos = 0
    batch: list[Point] = []

    with InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG, timeout=30_000) as client:
        write_api = client.write_api(write_options=SYNCHRONOUS)

        for r in registros:
            point = _build_point(categoria, subgrupo, tabla, r)
            if point is None:
                continue
            batch.append(point)
            if len(batch) >= BATCH_SIZE:
                _flush(write_api, batch)
                escritos += len(batch)
                batch = []

        if batch:
            _flush(write_api, batch)
            escritos += len(batch)

    logger.info(
        "InfluxDB write OK categoria=%s subgrupo=%s tabla=%s puntos=%d",
        categoria, subgrupo, tabla, escritos,
    )
    return escritos


def _flush(write_api, batch: list[Point]) -> None:
    try:
        write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=batch)
    except ApiException as exc:
        logger.warning("InfluxDB API error, reintentando 1 vez: %s", exc)
        write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=batch)