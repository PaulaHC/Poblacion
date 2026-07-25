"""Redaccion determinista de respuestas: cero LLM cuando el resultado de la
herramienta es interpretable directamente."""
import json
from typing import Optional

from langchain_core.messages import ToolMessage


def _parse(msg: ToolMessage) -> Optional[dict]:
    c = msg.content
    if isinstance(c, dict):
        return c
    try:
        return json.loads(c)
    except Exception:
        return None


def redactar(msg: ToolMessage) -> Optional[str]:
    res = _parse(msg)
    if res is None:
        return None
    tool = msg.name

    if not res.get("ok"):
        motivo = res.get("motivo")
        if motivo == "lugar_no_encontrado":
            return (f"No he encontrado ningun municipio ni provincia llamado "
                    f"\"{res.get('lugar', '')}\". Puedes comprobar el nombre?")
        if motivo == "sin_datos":
            lugar = res.get("lugar")
            return ("No tengo datos de ese indicador" +
                    (f" para {lugar}." if lugar else "."))
        if motivo == "indicador_desconocido":
            return ("No reconozco ese indicador. Puedo consultar poblacion, "
                    "renta, esperanza de vida, edad mediana, fecundidad, "
                    "natalidad, sectores de trabajo, estudios, estado civil y "
                    "migracion.")
        return None  # usa_distribucion / no_es_distribucion -> reintento vía LLM

    unidad = res.get("unidad", "")
    if tool == "obtener_dato":
        u = f" {unidad}" if unidad else ""
        # Sin articulo delante del indicador: evita discordancias de genero
        # ("La indicador de fecundidad").
        return (f"{res['indicador'].capitalize()} de {res['lugar']} "
                f"en {res['anio']}: {res['cifra']}{u}.")

    if tool == "hacer_ranking":
        filas = res.get("filas", [])
        if not filas:
            return None
        u = f" {unidad}" if unidad else ""
        etiqueta = "mayor" if res.get("orden") == "desc" else "menor"
        otra = "menor" if etiqueta == "mayor" else "mayor"
        lineas = [f"{i}. {f['nombre']}: {f['cifra']}{u}"
                  for i, f in enumerate(filas, 1)]
        anio = res.get("anio")
        en_anio = f" en {anio}" if anio else ""
        return (f"Ranking por {res['indicador']}{en_anio} "
                f"(de {etiqueta} a {otra}):\n" + "\n".join(lineas))

    if tool == "ver_distribucion":
        mayo = res.get("mayoritaria")
        if not mayo:
            return None
        u = f" {unidad}" if unidad else ""
        return (f"En {res['lugar']}, la categoria mayoritaria de "
                f"{res['indicador']} es {mayo['categoria']}, con "
                f"{mayo['cifra']}{u}. Si quieres, te doy el desglose completo.")
    return None
