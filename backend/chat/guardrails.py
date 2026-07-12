"""
Guardrail numérico: comprueba que las cifras de la respuesta del LLM aparecen en
lo que devolvieron las herramientas. Si el modelo se inventa un número, se
sustituye por un aviso seguro. Solo Python.
"""
import re
from typing import Optional

from langchain_core.messages import AIMessage, ToolMessage

_NUM = re.compile(r"\d[\d.,]*\d|\d")


def _a_float(token: str) -> Optional[float]:
    """Distingue separador decimal de miles por el nº de dígitos tras el último
    separador: 3 dígitos -> miles (16.517 = 16517); si no -> decimal (16.5)."""
    t = token.strip().rstrip(".,")
    if not re.fullmatch(r"\d[\d.,]*", t):
        return None
    if "." not in t and "," not in t:
        return float(t)
    sep = max(t.rfind("."), t.rfind(","))
    dec = t[sep + 1:]
    entero = re.sub(r"[.,]", "", t[:sep])
    if len(dec) == 3:
        return float(entero + dec)
    return float(entero + "." + dec)


def validar_cifras(messages) -> Optional[AIMessage]:
    """Devuelve None si la respuesta está bien fundamentada, o un AIMessage de
    reemplazo si detecta una cifra que no salió de ninguna herramienta."""
    ultimo = messages[-1]
    if not isinstance(ultimo, AIMessage) or not ultimo.content:
        return None

    permitidos = set()
    for m in messages:
        if isinstance(m, ToolMessage):
            for tok in _NUM.findall(str(m.content)):
                v = _a_float(tok)
                if v is not None:
                    permitidos.add(round(v, 2))

    for tok in _NUM.findall(ultimo.content):
        v = _a_float(tok)
        if v is None or round(v, 2) in permitidos:
            continue
        # tolera años y números pequeños de contexto (no son "datos")
        if v <= 3000 and v == int(v):
            continue
        return AIMessage(content=(
            "Perdona, no puedo confirmar esa cifra con los datos que tengo. "
            "¿Puedes reformular indicando el indicador, el lugar y el año?"
        ))
    return None