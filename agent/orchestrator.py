from langgraph.graph import StateGraph, END
from .state import AgentState
from .architect import architect_agent
from .coder import coder_agent
from .security import security_agent
from .tester import tester_agent

def after_architect(state: AgentState) -> str:
    """Architect後の分岐：承認→Coder、差し戻し→Architect"""
    if state["status"] == "approved":
        return "coder"
    elif state["status"] == "rejected":
        return "architect"
    return "end"

def after_coder(state: AgentState) -> str:
    """Coder後は必ずSecurityへ"""
    return "security"

def after_security(state: AgentState) -> str:
    """Security後の分岐：HIGH検出→Human承認待ち（end）、パス→Tester"""
    if state["status"] == "security_high":
        return "end"
    return "tester"

def after_tester(state: AgentState) -> str:
    """Tester後は常にend（tests_passed/tests_failed どちらもHuman確認）"""
    return "end"

def build_graph() -> StateGraph:
    """run コマンド用：Architectからスタート"""
    graph = StateGraph(AgentState)
    graph.add_node("architect", architect_agent)
    graph.add_node("coder", coder_agent)
    graph.add_node("security", security_agent)
    graph.add_node("tester", tester_agent)

    graph.set_entry_point("architect")

    graph.add_conditional_edges("architect", after_architect, {
        "coder": "coder",
        "architect": "architect",
        "end": END
    })
    graph.add_conditional_edges("coder", after_coder, {
        "security": "security"
    })
    graph.add_conditional_edges("security", after_security, {
        "tester": "tester",
        "end": END
    })
    graph.add_conditional_edges("tester", after_tester, {
        "end": END
    })

    return graph.compile()

def build_coder_graph() -> StateGraph:
    """approve コマンド用：Coderからスタート"""
    graph = StateGraph(AgentState)
    graph.add_node("coder", coder_agent)
    graph.add_node("security", security_agent)
    graph.add_node("tester", tester_agent)

    graph.set_entry_point("coder")

    graph.add_conditional_edges("coder", after_coder, {
        "security": "security"
    })
    graph.add_conditional_edges("security", after_security, {
        "tester": "tester",
        "end": END
    })
    graph.add_conditional_edges("tester", after_tester, {
        "end": END
    })

    return graph.compile()

def build_tester_graph() -> StateGraph:
    """security-approve コマンド用：Testerからスタート"""
    graph = StateGraph(AgentState)
    graph.add_node("tester", tester_agent)

    graph.set_entry_point("tester")

    graph.add_conditional_edges("tester", after_tester, {
        "end": END
    })

    return graph.compile()