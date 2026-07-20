from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage, SystemMessage
from langgraph.graph import START, END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver
from langchain_ollama import ChatOllama

import db
from .tools import TOOLS
from .guardrails import validar_cifras

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


_llm = ChatOllama(
    model=db.OLLAMA_MODEL,
    base_url=db.OLLAMA_URL,
    temperature=0,
    reasoning=False,         
    client_kwargs={"timeout": 300},
).bind_tools(TOOLS)


async def n_agente(state: AgentState) -> dict:
    respuesta = await _llm.ainvoke([SYSTEM] + state["messages"])
    return {"messages": [respuesta]}


async def n_guardrails(state: AgentState) -> dict:
    corregida = validar_cifras(state["messages"])
    return {"messages": [corregida]} if corregida else {}


def make_graph():
    g = StateGraph(AgentState)
    g.add_node("agente", n_agente)
    g.add_node("herramientas", ToolNode(TOOLS))
    g.add_node("guardrails", n_guardrails)

    g.add_edge(START, "agente")
    g.add_conditional_edges(
        "agente",
        tools_condition,
        {"tools": "herramientas", END: "guardrails"},
    )
    g.add_edge("herramientas", "agente")
    g.add_edge("guardrails", END)
    return g.compile(checkpointer=MemorySaver())