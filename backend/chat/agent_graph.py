from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Annotated, Awaitable, Callable, Literal, Optional, TypedDict

import httpx
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger("poview.agent")

# ============================================================
#  Configuración
# ============================================================
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_ROUTER_MODEL = os.environ.get("OLLAMA_ROUTER_MODEL", "qwen3:1.7b")
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "300"))

MAX_RETRIES = 1   
MAX_ERRORS = 2   


# ============================================================
#  1. Esquemas Pydantic
# ============================================================
class Intencion(BaseModel):
    ruta: Literal["consulta_datos", "conversacion", "rechazar"] = "conversacion"
    indicador: Optional[str] = Field(
        None, description="poblacion|renta|esperanza_vida|edad_mediana|fecundidad|trabajo")
    lugar: Optional[str] = None
    anio: Optional[int] = None
    ranking: bool = False
    orden: Literal["desc", "asc"] = "desc"

    @field_validator("indicador", "lugar", mode="before")
    @classmethod
    def _vaciar_nulos(cls, v):
        if isinstance(v, str) and v.strip().lower() in {"null", "none", "na", "n/a", ""}:
            return None
        return v

    @field_validator("anio", mode="before")
    @classmethod
    def _coaccionar_anio(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip().lower()
            if s in {"null", "none", ""}:
                return None
            m = re.search(r"\d{4}", s)
            return int(m.group()) if m else None
        return v

    @field_validator("orden", mode="before")
    @classmethod
    def _coaccionar_orden(cls, v):
        return "asc" if isinstance(v, str) and v.strip().lower().startswith("asc") else "desc"

    @field_validator("ranking", mode="before")
    @classmethod
    def _coaccionar_ranking(cls, v):
        if isinstance(v, str):
            return v.strip().lower() in {"true", "1", "si", "sí", "yes"}
        return bool(v)


# ============================================================
#  2. Estado del grafo
# ============================================================
class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]

    intent: dict                      
    routing_decision: Optional[str]   
    retrieved: list[dict]             
    draft: str                        
    guard_ok: bool                   
    guard_feedback: Optional[str]     

    retry_count: int                  
    error_count: int                  
    last_error: Optional[str]        


# ============================================================
#  Utilidades LLM
# ============================================================
async def _ollama(messages: list[dict], *, fmt: Optional[str] = None,
                  temperature: float = 0.0, model: Optional[str] = None) -> str:
    body = {"model": model or OLLAMA_MODEL, "messages": messages, "stream": False,
            "think": False,
            "options": {"temperature": temperature, "num_ctx": 4096}}
    if fmt:
        body["format"] = fmt
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as cli:
        r = await cli.post(f"{OLLAMA_URL}/api/chat", json=body)
        r.raise_for_status()
        return r.json()["message"]["content"].strip()


def _ultimo_humano(messages: list[AnyMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            return m.content
    return ""


def _historial(messages: list[AnyMessage], n: int = 6) -> list[dict]:
    out = []
    for m in messages[-n:]:
        role = "user" if isinstance(m, HumanMessage) else "assistant"
        out.append({"role": role, "content": m.content})
    return out


# ============================================================
def _norm(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _lista_natural(items: list[str]) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " y " + items[-1]


def _pide_dominante(pregunta: str) -> bool:
    q = _norm(pregunta)
    if any(k in q for k in ("mayoritario", "principal", "predomin", "mas empresas",
                            "mas importante", "que mas")):
        return True
    return "cual" in q and "sector" in q and "sectores" not in q


def _redactar_trabajo(pregunta: str, rows: list[dict]) -> str:
    lugar = rows[0]["lugar"]
    anio = rows[0]["anio"]
    sectores = [r["sector"] for r in rows]
    dominante = sectores[0]
    if _pide_dominante(pregunta):
        return f"El sector con más empresas en {lugar} es {dominante} (datos de {anio})."
    return (f"En {lugar}, los sectores con más empresas son {_lista_natural(sectores)} "
            f"(datos de {anio}). El mayoritario es {dominante}.")


def _redactar_ranking(rows: list[dict], orden: str) -> str:
    etiqueta = rows[0].get("etiqueta") or "valor"
    sentido = "de menor a mayor" if orden == "asc" else "de mayor a menor"
    partes = "; ".join(f"{i}) {r['lugar']}: {r['texto']}"
                       for i, r in enumerate(rows, 1))
    return f"Ranking por {etiqueta} ({sentido}): {partes}."


def _redactar_datos(pregunta: str, rows: list[dict], intent: dict) -> str:
    if not rows:
        return "No encontré datos para esa consulta."
    if "sector" in rows[0]:                      
        return _redactar_trabajo(pregunta, rows)
    if intent.get("ranking") and len(rows) > 1:  
        return _redactar_ranking(rows, intent.get("orden", "desc"))
    r = rows[0]                                   
    etiqueta = (r.get("etiqueta") or "Valor").capitalize()
    return f"{etiqueta} de {r['lugar']} en {r['anio']}: {r['texto']}."


# ============================================================
_RANK_CUES = (
    "ranking", "top ", "clasificacion", "ordena", "lista de", "listado",
    "mas poblad", "menos poblad", "mas grandes", "mas pequen", "mas pobladas",
    "los mayores", "los menores", "las mayores", "las menores",
    "cuales son los", "cuales son las", "que municipios", "que provincias",
    "mayor poblacion", "menor poblacion", "mas habitantes", "menos habitantes",
    "mas ricos", "mas pobres", "mas alta", "mas baja", "mejores", "peores",
)
_SINGLE_CUES = (
    "cuanto", "cuanta", "cuantos", "cuantas", "que poblacion", "poblacion de",
    "tiene", "cual es", "renta de", "esperanza de vida de", "edad mediana de",
)
_ASC_CUES = ("menos", "menor", "mas pequen", "mas baja", "mas bajo", "mas pobre",
             "ascendente", "peor")


def _saneo_ranking(pregunta: str, lugar: Optional[str], llm_ranking: bool) -> bool:
    q = _norm(pregunta)
    if any(c in q for c in _RANK_CUES):        
        return True
    if lugar and any(c in q for c in _SINGLE_CUES):   
        return False
    return bool(llm_ranking)                  


def _saneo_orden(pregunta: str, llm_orden: Optional[str]) -> str:
    q = _norm(pregunta)
    if any(c in q for c in _ASC_CUES):
        return "asc"
    if "mayor" in q or "mas " in q or "desc" in q:
        return "desc"
    return llm_orden or "desc"


# ============================================================
#  Captura excepciones de nodo.
# ============================================================
def resiliente(fn: Callable[[AgentState], Awaitable[dict]]):
    async def wrapper(state: AgentState) -> dict:
        try:
            return await fn(state)
        except Exception as exc:                      
            logger.exception("Fallo en nodo %s", fn.__name__)
            return {
                "last_error": f"{fn.__name__}: {exc}",
                "error_count": state.get("error_count", 0) + 1,
            }
    wrapper.__name__ = fn.__name__
    return wrapper


# ============================================================
#  Prompts
# ============================================================
ROUTER_SYSTEM = (
    "Clasifica la pregunta de un usuario sobre datos demográficos del INE de España. "
    "Devuelve SOLO JSON: "
    '{"ruta":"<consulta_datos|conversacion|rechazar>","indicador":"<poblacion|renta|'
    'esperanza_vida|edad_mediana|fecundidad|trabajo|null>","lugar":"<nombre|null>","anio":<año|null>,'
    '"ranking":<true|false>,"orden":"<desc|asc>"}\n'
    "indicador=poblacion para habitantes/población/padrón; renta para ingresos; "
    "esperanza_vida; edad_mediana; fecundidad; trabajo para sectores/empresas/economía/empleo.\n"
    "ruta=consulta_datos: pide una cifra, ranking, sector o evolución.\n"
    "ruta=conversacion: saludo, agradecimiento o cómo usar la app.\n"
    "ruta=rechazar: tema ajeno a demografía del INE o contenido inapropiado.\n"
    "Si omite lugar/indicador/año y es un seguimiento, hereda del contexto del historial."
)
GEN_DATOS_SYSTEM = (
    "Asistente de datos del INE. Responde SOLO con la información del bloque 'Datos'. "
    "Para cada dato usa EXACTAMENTE su campo 'texto' (cifra ya formateada o nombre de "
    "sector): no lo reformatees ni añadas decimales como '.0'. PROHIBIDO inventar o "
    "estimar números o categorías. Frase directa y breve, en el idioma del usuario."
)
GEN_CHAT_SYSTEM = (
    "Asistente de PoView (datos demográficos del INE). Solo saludas, agradeces o explicas "
    "cómo usar la app y qué indicadores hay (población, renta, esperanza de vida, edad "
    "mediana, fecundidad y sectores de trabajo). NO afirmes datos concretos sobre ningún "
    "lugar (cifras, sectores económicos, comparativas o rankings): para eso hay que "
    "consultar la base de datos. Si te piden un dato que no tienes, dilo con sinceridad y "
    "sugiere reformular. Responde con cordialidad y brevedad."
)


# ============================================================
#  3. NODOS
# ============================================================
@resiliente
async def n_router(state: AgentState) -> dict:
    pregunta = _ultimo_humano(state["messages"])
    raw = await _ollama(
        [{"role": "system", "content": ROUTER_SYSTEM},
         *_historial(state["messages"]),
         {"role": "user", "content": f"Pregunta: {pregunta}"}],
        fmt="json",
        model=OLLAMA_ROUTER_MODEL,   
    )
    try:
        intent = Intencion.model_validate_json(raw)
    except (ValidationError, ValueError):
        logger.warning("Intención inválida del LLM: %s", raw)
        intent = Intencion()

    data = intent.model_dump()
    data["ranking"] = _saneo_ranking(pregunta, intent.lugar, intent.ranking)
    data["orden"] = _saneo_orden(pregunta, intent.orden)

    logger.info("[router] ruta=%s intent=%s", intent.ruta, data)
    return {"intent": data,
            "routing_decision": intent.ruta,
            "retry_count": 0, "guard_feedback": None}


RecuperadorDatos = Callable[[dict], Awaitable[list[dict]]]


def construir_recuperar(recuperar_datos: RecuperadorDatos):
    @resiliente
    async def n_recuperar(state: AgentState) -> dict:
        rows = await recuperar_datos(state["intent"])
        logger.info("[recuperar] %d filas", len(rows))
        return {"retrieved": rows}
    return n_recuperar


@resiliente
async def n_generar(state: AgentState) -> dict:
    pregunta = _ultimo_humano(state["messages"])
    rows = state.get("retrieved", [])
    feedback = state.get("guard_feedback")

    if state.get("routing_decision") == "consulta_datos":
        contenido = (f"Pregunta: {pregunta}\n"
                     f"Datos (únicos válidos): {rows}")
        if feedback:
            contenido += f"\nCorrige estos problemas de la respuesta anterior: {feedback}"
        mensajes = [{"role": "system", "content": GEN_DATOS_SYSTEM},
                    {"role": "user", "content": contenido}]
    else:
        mensajes = [{"role": "system", "content": GEN_CHAT_SYSTEM},
                    *_historial(state["messages"]),
                    {"role": "user", "content": f"Pregunta: {pregunta}"}]

    draft = await _ollama(mensajes)
    return {"draft": draft, "retry_count": state.get("retry_count", 0) + 1}


_NUM = re.compile(r"\d[\d.\,]*")


def _a_num(token: str) -> Optional[float]:
    t = token.strip().strip(".,")
    if not any(c.isdigit() for c in t):
        return None
    m = re.search(r"[.,](\d{1,2})$", t)
    if m:
        ent = t[:m.start()].replace(".", "").replace(",", "")
        t = f"{ent}.{m.group(1)}"
    else:
        t = re.sub(r"[.,]", "", t)   
    try:
        return float(t)
    except ValueError:
        return None


def _validar(draft: str, rows: list[dict], routing: Optional[str]) -> list[str]:
    problemas: list[str] = []
    if not draft or len(draft.strip()) < 2:
        problemas.append("respuesta vacía")
    if len(draft) > 1500:
        problemas.append("respuesta demasiado larga")

    if routing == "consulta_datos" and rows:
        permitidos = {round(float(v)) for r in rows for v in r.values()
                      if isinstance(v, (int, float))}
        for tok in _NUM.findall(draft):
            n = _a_num(tok)
            if n is None or abs(n) < 4:  
                continue
            if not any(abs(round(n) - p) <= max(1, abs(p) * 0.01) for p in permitidos):
                problemas.append(f"cifra no respaldada por los datos: {tok}")
                break
    return problemas


@resiliente
async def n_guardrails(state: AgentState) -> dict:
    draft = state.get("draft", "")
    problemas = _validar(draft, state.get("retrieved", []), state.get("routing_decision"))
    if not problemas:
        return {"guard_ok": True, "messages": [AIMessage(content=draft)]}
    logger.warning("[guardrails] rechazado: %s", problemas)
    return {"guard_ok": False, "guard_feedback": "; ".join(problemas)}


@resiliente
async def n_responder_datos(state: AgentState) -> dict:
    pregunta = _ultimo_humano(state["messages"])
    rows = state.get("retrieved", [])
    intent = state.get("intent") or {}
    texto = _redactar_datos(pregunta, rows, intent)
    return {"messages": [AIMessage(content=texto)], "guard_ok": True}


@resiliente
async def n_sin_datos(state: AgentState) -> dict:
    """InfluxDB devolvió vacío: respuesta FIJA, sin invocar al LLM.
    (Evita que el modelo invente cifras y ahorra una llamada lenta en CPU.)"""
    intent = state.get("intent") or {}
    lugar = intent.get("lugar")
    indicador = intent.get("indicador") or "ese indicador"
    donde = f" para «{lugar}»" if lugar else ""
    texto = (
        f"No encuentro datos de {indicador}{donde} en la base del INE cargada. "
        "Puede que el lugar no exista con ese nombre, que el indicador no tenga "
        "datos para ese año, o que se trate de un tema fuera de los disponibles "
        "(población, renta, esperanza de vida, edad mediana, fecundidad y sectores de "
        "trabajo). Prueba a reformular con otro municipio/provincia, indicador o año."
    )
    logger.info("[sin_datos] respuesta fija (intent=%s)", intent)
    return {"messages": [AIMessage(content=texto)], "guard_ok": True}


@resiliente
async def n_fallback(state: AgentState) -> dict:
    rows = state.get("retrieved", [])
    if rows:
        texto = ("No puedo garantizar una redacción fiable ahora mismo. "
                 f"Datos disponibles: {rows[:5]}")
    else:
        texto = "No he podido componer una respuesta fiable. Reformula la pregunta, por favor."
    return {"messages": [AIMessage(content=texto)], "guard_ok": True}


async def n_rechazar(state: AgentState) -> dict:
    texto = ("Solo puedo ayudarte con datos demográficos del INE de España "
             "(población, renta, esperanza de vida, edad mediana, fecundidad y "
             "sectores de trabajo).")
    return {"messages": [AIMessage(content=texto)]}


async def n_manejar_error(state: AgentState) -> dict:
    logger.error("[error] %s", state.get("last_error"))
    texto = "Lo siento, ha ocurrido un problema procesando tu mensaje. Inténtalo de nuevo."
    return {"messages": [AIMessage(content=texto)], "last_error": None}


# ============================================================
#  4. ENRUTADO CONDICIONAL
# ============================================================
def ruta_router(state: AgentState) -> str:
    if state.get("last_error"):
        return "error"
    return state.get("routing_decision") or "conversacion"


def ruta_tras_recuperar(state: AgentState) -> str:
    if state.get("last_error"):
        return "error"
    if not state.get("retrieved"):
        return "sin_datos"
    return "responder_datos"


def ruta_tras_generar(state: AgentState) -> str:
    return "error" if state.get("last_error") else "guardrails"


def ruta_guardrails(state: AgentState) -> str:
    if state.get("last_error"):
        return "error"
    if state.get("guard_ok"):
        return "fin"
    if state.get("retry_count", 0) <= MAX_RETRIES:
        return "reintentar"
    return "fallback"


# ============================================================
#  Ensamblado del grafo
# ============================================================
def make_graph(recuperar_datos: RecuperadorDatos):
    g = StateGraph(AgentState)

    g.add_node("router", n_router)
    g.add_node("recuperar", construir_recuperar(recuperar_datos))
    g.add_node("responder_datos", n_responder_datos)
    g.add_node("generar", n_generar)
    g.add_node("guardrails", n_guardrails)
    g.add_node("sin_datos", n_sin_datos)
    g.add_node("fallback", n_fallback)
    g.add_node("rechazar", n_rechazar)
    g.add_node("manejar_error", n_manejar_error)

    g.add_edge(START, "router")
    g.add_conditional_edges("router", ruta_router, {
        "consulta_datos": "recuperar",
        "conversacion": "generar",
        "rechazar": "rechazar",
        "error": "manejar_error",
    })
    g.add_conditional_edges("recuperar", ruta_tras_recuperar, {
        "responder_datos": "responder_datos",
        "sin_datos": "sin_datos",
        "error": "manejar_error",
    })
    g.add_conditional_edges("generar", ruta_tras_generar,
                            {"guardrails": "guardrails", "error": "manejar_error"})
    g.add_conditional_edges("guardrails", ruta_guardrails, {
        "fin": END,
        "reintentar": "generar",
        "fallback": "fallback",
        "error": "manejar_error",
    })
    g.add_edge("responder_datos", END)
    g.add_edge("sin_datos", END)
    g.add_edge("rechazar", END)
    g.add_edge("fallback", END)
    g.add_edge("manejar_error", END)

    return g.compile(checkpointer=MemorySaver())


# ============================================================
#  Ejemplo de uso (demo manual)
# ============================================================
if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO)

    # Recuperador DUMMY: aquí enchufas tu InfluxStats determinista real.
    async def recuperar_dummy(intent: dict) -> list[dict]:
        return [{"lugar": intent.get("lugar") or "España", "anio": intent.get("anio"),
                 "valor": 24300, "unidad": "€"}]

    grafo = make_graph(recuperar_dummy)

    async def main():
        # recursion_limit: BACKSTOP DURO contra bucles infinitos.
        config = {"configurable": {"thread_id": "demo-1"}, "recursion_limit": 25}
        r = await grafo.ainvoke(
            {"messages": [HumanMessage(content="renta de Soria en 2020")]},
            config=config,
        )
        logger.info("Respuesta: %s", r["messages"][-1].content)

    asyncio.run(main())