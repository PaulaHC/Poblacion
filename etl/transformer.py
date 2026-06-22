import re
import unicodedata

from datasets import PROVINCIAS


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return " ".join("".join(c for c in s if unicodedata.category(c) != "Mn").split())


_PROV_POR_NOMBRE: dict[str, str] = {}
for _cod, (_nom, _com, _ab) in PROVINCIAS.items():
    _PROV_POR_NOMBRE[_norm(_nom)] = _cod

_PROV_POR_NOMBRE.update({
    "a coruna": "15", "coruna a": "15", "la coruna": "15", "coruna": "15",
    "illes balears": "07", "balears illes": "07", "islas baleares": "07", "baleares": "07",
    "la rioja": "26", "rioja la": "26", "rioja": "26",
    "araba alava": "01", "alava araba": "01", "alava": "01", "araba": "01",
    "gipuzkoa": "20", "guipuzcoa": "20", "bizkaia": "48", "vizcaya": "48",
    "ourense": "32", "orense": "32", "girona": "17", "gerona": "17",
    "lleida": "25", "lerida": "25", "castello": "12", "castellon": "12",
    "alacant": "03", "alicante": "03", "valencia": "46", "valencia valencia": "46",
    "ceuta": "51", "melilla": "52", "nafarroa": "31",
    "las palmas": "35", "santa cruz de tenerife": "38",
})


def _cod_provincia_por_nombre(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    m = re.match(r'^(\d{2})\b', raw)
    if m and m.group(1) in PROVINCIAS:
        return m.group(1)
    return _PROV_POR_NOMBRE.get(_norm(raw), "")


def parse_municipio(raw: str) -> tuple[str, str]:

    raw = raw.strip().strip('"')
    m = re.match(r'^(\d{5})\s*(.*)', raw)
    if m:
        return m.group(1), m.group(2).strip()
    return "", raw


def getProvincias(cod_municipio: str) -> dict:

    cod_provincia = cod_municipio[:2] if len(cod_municipio) >= 2 else "00"
    prov = PROVINCIAS.get(cod_provincia, ("Desconocida", "Desconocida", "UNK"))
    return {
        "cod_provincia":     cod_provincia,
        "provincia":         prov[0],
        "comunidad":         prov[1],
    }


def parsear_valor(raw: str) -> float | None:

    raw = raw.strip()
    if raw in ("", "-", "..", "N/A"):
        return None
    raw = raw.replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def parsear_periodo(raw: str) -> int | None:

    raw = raw.strip()
    m = re.search(r'\b(19|20)\d{2}\b', raw)
    if m:
        return int(m.group())
    return None


def buscar_columna(cols: dict, *candidatos: str) -> str:

    for cand in candidatos:
        for k in cols:
            if cand.lower() in k.lower():
                return cols[k]
    return ""


def transformar_rows(subgrupo: str, rows: list[list[str]]) -> list[dict]:

    if len(rows) < 2:
        return []

    header = [h.replace("\ufeff", "").strip() for h in rows[0]]
    registros = []

    for row in rows[1:]:
        if len(row) != len(header):
            continue
        cols = dict(zip(header, [c.strip() for c in row]))

        valor = parsear_valor(cols.get("Total", ""))
        if valor is None:
            continue

        anio = parsear_periodo(cols.get("Periodo", ""))
        if anio is None:
            continue

        if subgrupo != "renta":
            municipio_raw = buscar_columna(cols, "Municipios", "Municipio")
            if not municipio_raw:
                continue
            cod, nombre = parse_municipio(municipio_raw)
            if not cod:
                continue

            prov = getProvincias(cod)
            base = {
                "cod_municipio": cod,
                "municipio":     nombre,
                "periodo":       anio,
                "valor":         valor,
                **prov,
            }
        else:
            if buscar_columna(cols, "Islas", "Isla"):
                continue
            cod_prov = _cod_provincia_por_nombre(buscar_columna(cols, "Provincias", "Provincia"))
            if not cod_prov:
                continue
            nombre_prov, comunidad, _ab = PROVINCIAS[cod_prov]
            base = {
                "periodo":       anio,
                "valor":         valor,
                "cod_provincia": cod_prov,
                "provincia":     nombre_prov,
                "comunidad":     comunidad,
            }

        if subgrupo in ("municipios", "edad_mediana"):
            registros.append({
                **base,
                "sexo": cols.get("Sexo", "Total").strip() or "Total",
            })

        elif subgrupo == "natalidad":
            registros.append(base)

        elif subgrupo == "fecundidad":
            registros.append(base)

        elif subgrupo == "mortalidad":
            registros.append({
                **base,
                "sexo":       cols.get("Sexo", "Total").strip() or "Total",
                "grupo_edad": buscar_columna(cols, "Edad", "Grupo de edad", "Grupos de edad") or "todas",
            })

        elif subgrupo == "esperanza_vida":
            registros.append({
                **base,
                "sexo": cols.get("Sexo", "Total").strip() or "Total",
            })

        elif subgrupo == "migracion":
            registros.append({
                **base,
                "sexo":         cols.get("Sexo", "Total").strip() or "Total",
                "nacionalidad": buscar_columna(cols, "Nacionalidad", "Nacional") or "Total",
                "grupo_edad":   buscar_columna(cols, "Edad", "Grupo de edad") or "todas",
            })

        elif subgrupo == "trabajo":
            registros.append({
                **base,
                "sector": buscar_columna(cols, "CNAE", "Actividad", "Grupos CNAE") or "Total",
            })

        elif subgrupo == "estudios":
            registros.append({
                **base,
                "sexo":          cols.get("Sexo", "Total").strip() or "Total",
                "nivel_estudio": buscar_columna(cols, "Nivel de estudios", "Estudios", "Nivel") or "Total",
                "grupo_edad":    buscar_columna(cols, "Edad", "Grupo de edad") or "todas",
            })

        elif subgrupo == "estadoCivil":
            registros.append({
                **base,
                "sexo":         cols.get("Sexo", "Total").strip() or "Total",
                "estado_civil": buscar_columna(cols, "Estado civil", "Estado") or "Total",
                "grupo_edad":   buscar_columna(cols, "Edad", "Grupo de edad") or "todas",
            })

        elif subgrupo == "renta":
            indicador = buscar_columna(cols, "Indicadores de renta media", "Indicadores") or ""
            if "renta bruta media por persona" in _norm(indicador):
                registros.append(base)

        else:
            registros.append(base)

    return registros