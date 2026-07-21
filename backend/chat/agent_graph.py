import os
from typing import Annotated, TypedDict

from langchain_core.messages import (AIMessage, AnyMessage, HumanMessage,
                                     SystemMessage, ToolMessage)
from langgraph.graph import START, END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from langchain_ollama import ChatOllama

import db
from .tools import TOOLS
from .guardrails import validar_cifras
from .preclasificador import preclasificar
from .plantillas import redactar

FASTPATH = os.environ.get("CHAT_FASTPATH", "1") == "1"
MAX_HISTORIAL = 12

SYSTEM = SystemMessage(content=(
    "Eres el asistente de PoView, sobre datos demográficos del INE en España. "
    "Tienes tres herramientas:\n"
    "- obtener_dato: UNA cifra (población, renta, esperanza de vida, edad "
    "mediana, fecundidad, natalidad).\n"
    "- hacer_ranking: ordenar municipios o provincias por una de esas cifras.\n"
    "- ver_distribucion: reparto por categoría (trabajo/sector, nivel de "
    "estudios, estado civil, migración por nacionalidad).\n"
    "Reglas estrictas:\n"
    "1. Para CUALQUIER dato numérico usa una herramienta; nunca respondas cifras "
    "de memoria ni las estimes.\n"
    "2. Copia las cifras EXACTAMENTE como te las da la herramienta (campo 'cifra') "
    "y añade la unidad del campo 'unidad'. No recalcules ni reformatees.\n"
    "3. En ver_distribucion, di por defecto SOLO la categoría mayoritaria "
    "(campo 'mayoritaria'); ofrece el desglose completo únicamente si el usuario "
    "lo pide.\n"
    "4. Si una herramienta devuelve ok=false con motivo 'usa_distribucion' o "
    "'no_es_distribucion', reintenta con la herramienta correcta. Con otros "
    "motivos (lugar_no_encontrado, sin_datos, indicador_desconocido), explícalo "
    "con naturalidad y no inventes.\n"
    "5. Si la pregunta no trata de demografía del INE, dilo brevemente.\n"
    "6. Escribe en texto plano. NO uses Markdown: nada de asteriscos, "
    "almohadillas ni guiones de lista.\n"
    "Responde en español, de forma clara y breve."
))


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    fastpath: bool


_llm = ChatOllama(
    model=db.OLLAMA_MODEL,
    base_url=db.OLLAMA_URL,
    temperature=0,
    reasoning=False,
    num_ctx=4096,
    num_predict=512,
    keep_alive="1h",
    client_kwargs={"timeout": 300},
).bind_tools(TOOLS)


def _recortar(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Ultimos MAX_HISTORIAL mensajes sin romper pares tool_call/tool_result."""
    corte = messages[-MAX_HISTORIAL:]
    while corte and isinstance(corte[0], ToolMessage):
        corte = corte[1:]
    return corte


# ---- Nodos ---------------------------------------------------------
def n_pre(state: AgentState) -> dict:
    ultimo = state["messages"][-1]
    if FASTPATH and isinstance(ultimo, HumanMessage):
        tc = preclasificar(str(ultimo.content))
        if tc is not None:
            return {"messages": [tc], "fastpath": True}
    return {"fastpath": False}


async def n_agente(state: AgentState) -> dict:
    respuesta = await _llm.ainvoke([SYSTEM] + _recortar(state["messages"]))
    return {"messages": [respuesta], "fastpath": False}


def n_redactor(state: AgentState) -> dict:
    ultimo = state["messages"][-1]
    if isinstance(ultimo, ToolMessage):
        texto = redactar(ultimo)
        if texto is not None:
            return {"messages": [AIMessage(content=texto)]}
    return {}


async def n_guardrails(state: AgentState) -> dict:
    corregida = validar_cifras(state["messages"])
    return {"messages": [corregida]} if corregida else {}


# ---- Rutas ---------------------------------------------------------
def r_pre(state: AgentState) -> str:
    return "herramientas" if state.get("fastpath") else "agente"


def r_agente(state: AgentState) -> str:
    ultimo = state["messages"][-1]
    return "herramientas" if getattr(ultimo, "tool_calls", None) else "guardrails"


def r_redactor(state: AgentState) -> str:
    # Si la plantilla generó respuesta -> guardrails; si no, redacta el LLM.
    return "guardrails" if isinstance(state["messages"][-1], AIMessage) else "agente"


def make_graph():
    g = StateGraph(AgentState)
    g.add_node("pre", n_pre)
    g.add_node("agente", n_agente)
    g.add_node("herramientas", ToolNode(TOOLS))
    g.add_node("redactor", n_redactor)
    g.add_node("guardrails", n_guardrails)

    g.add_edge(START, "pre")
    g.add_conditional_edges("pre", r_pre,
                            {"herramientas": "herramientas", "agente": "agente"})
    g.add_conditional_edges("agente", r_agente,
                            {"herramientas": "herramientas", "guardrails": "guardrails"})
    g.add_edge("herramientas", "redactor")
    g.add_conditional_edges("redactor", r_redactor,
                            {"guardrails": "guardrails", "agente": "agente"})
    g.add_edge("guardrails", END)
    return g.compile(checkpointer=MemorySaver())
