from langchain_core.messages import HumanMessage

from .agent_graph import make_graph

_graph = make_graph()


async def responder_chat(mensaje: str, thread_id: str) -> dict:
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 8,  
    }
    estado = await _graph.ainvoke(
        {"messages": [HumanMessage(content=mensaje)]}, config
    )
    return {"text": estado["messages"][-1].content}