"""LangGraph 연결과 한 턴 실행 (F3005)"""
from langgraph.graph import END, START, StateGraph

from agent.nodes import analyze, plan, work
from agent.respond import respond
from agent.save import save
from agent.review import judge, places, replan, route_after_judge
from agent.state import AgentState, new_state, trim_history

_sessions = {}  # session_id -> {"history", "conditions", "tool_cache"}  (대화 맥락, 서버가 켜진 동안 유지)


def _after_analyze(state):
    if state.get("fatal_error"):
        return "respond"
    if state.get("save_target"):
        return "save"
    return END if state.get("answer") else "plan"  # answer가 이미 있으면 되묻기·안내라서 Tool 없이 끝낸다


def _after_work(state):
    return "respond" if state.get("fatal_error") else "judge"


def build_graph():
    g = StateGraph(AgentState)
    for name, fn in (("analyze", analyze), ("plan", plan), ("work", work), ("judge", judge),
                     ("places", places), ("replan", replan), ("respond", respond), ("save", save)):
        g.add_node(name, fn)
    g.add_edge(START, "analyze")
    g.add_conditional_edges("analyze", _after_analyze, {"respond": "respond", "plan": "plan", "save": "save", END: END})
    g.add_edge("plan", "work")
    g.add_conditional_edges("work", _after_work, {"respond": "respond", "judge": "judge"})
    g.add_conditional_edges("judge", route_after_judge, {"places": "places", "replan": "replan",
                                                         "respond": "respond"})
    g.add_edge("replan", "work")
    g.add_edge("places", "respond")
    g.add_edge("respond", END)
    g.add_edge("save", END)
    return g.compile()


GRAPH = build_graph()


def run_turn(session_id, user_message):
    """한 번의 대화 요청을 처리하고 최종 상태를 돌려준다."""
    ctx = _sessions.get(session_id, {})
    state = new_state(session_id, user_message, ctx.get("history"), ctx.get("conditions"), ctx.get("tool_cache"),
                      ctx.get("last"))
    final = GRAPH.invoke(state)
    history = trim_history(ctx.get("history", []) + [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": final["answer"][:300]}])
    last = ctx.get("last")
    if final.get("candidates"):  # 추천이 나온 턴의 결과만 '직전 추천'으로 기억한다
        last = {"candidates": [{k: j[k] for k in ("spot_id", "name", "grade", "wave_max_m", "wind_max_ms")}
                               for j in final["candidates"]],
                "conditions": dict(final["conditions"])}
    _sessions[session_id] = {"history": history, "conditions": final["conditions"],
                             "tool_cache": final["tool_cache"], "last": last}
    return final


def reset_session(session_id):
    _sessions.pop(session_id, None)