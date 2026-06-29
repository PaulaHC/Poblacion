from langchain_core.messages import HumanMessage

import db
from .agent_graph import make_graph
from .retriever import InfluxRetriever

_GRAPH = make_graph(InfluxRetriever())


async def responder_chat(message: str, thread_id: str) -> dict:
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 25,  
    }
    final = await _GRAPH.ainvoke(
        {"messages": [HumanMessage(content=message)]},
        config=config,
    )
    msgs = final.get("messages", [])
    texto = msgs[-1].content if msgs else "(sin respuesta)"
    lugar = (final.get("intent") or {}).get("lugar")
    db.logger.debug("[chat] thread=%s -> %s", thread_id, texto)
    return {"text": texto, "lugar": lugar}


__all__ = ["responder_chat"]