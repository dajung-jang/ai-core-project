"""판단 이후 단계: judge(수식) -> places(보조 정보) -> replan(규칙)"""
import config
from agent import judge as J
from agent.nodes import _execute, build_tasks, chain_beach_args, traced
from agent.state import cache_key
from events import bus
from spots import SPOTS

REGIONS = sorted({s["region"] for s in SPOTS})
GEO_ORDER = ["양양", "포항", "부산", "제주"]  # 북→남. 시작 지역에서 가까운 순으로 넓혀 간다
PLACES_PER_KIND = 3


def untried_regions(state):
    tried = state.get("tried_regions", [])
    start = GEO_ORDER.index(tried[0]) if tried and tried[0] in GEO_ORDER else 0
    rest = [r for r in REGIONS if r not in tried]
    return sorted(rest, key=lambda r: abs(GEO_ORDER.index(r) - start) if r in GEO_ORDER else 99)


# ---------- judge ----------
@traced("judge")
def judge(state):
    c = state["conditions"]
    region = state["tried_regions"][-1]
    level = c.get("level") or "초보"
    wave_task, beach_task = build_tasks(c, region)
    wave_e = state["tool_cache"].get(cache_key(wave_task["tool"], wave_task["args"]), {})
    beach_args = chain_beach_args(beach_task["args"], wave_e)  # work 단계에서 실제로 호출한 입력과 같은 값
    beach_e = state["tool_cache"].get(cache_key(beach_task["tool"], beach_args), {})

    new = []
    for spot in [s for s in SPOTS if s["region"] == region]:
        sid = spot["id"]
        wave = (wave_e.get("summary", {}).get("spots", {}).get(sid) or {}).get("max_wave_m")
        b = beach_e.get("summary", {}).get("spots", {}).get(sid) or {}
        j = J.judge_spot(sid, spot["name"], wave, b.get("max_wind_ms"), b.get("observed_wave_m"), level)
        if j["grade"] == J.UNKNOWN:  # 값을 못 얻은 이유를 구체적으로 남긴다
            why = []
            if not wave_e.get("ok"):
                why.append(wave_e.get("error", {}).get("message", "파고 예보를 조회하지 못했습니다."))
            if not beach_e.get("ok"):
                why.append(beach_e.get("error", {}).get("message", "해변 날씨를 조회하지 못했습니다."))
            elif b.get("error_code"):
                why.append(b.get("error_message") or "해변 날씨를 조회하지 못했습니다.")
            if why:
                j["reasons"] = why
        j["region"] = region
        j["observed_water_c"] = b.get("observed_water_c")
        new.append(j)

    ids = {j["spot_id"] for j in new}
    judgments = [j for j in state.get("judgments", []) if j["spot_id"] not in ids] + new
    candidates, excluded = J.rank(judgments)
    bus.emit(state["session_id"], bus.JUDGE_RESULT, {
        "region": region, "level": level,
        "spots": [{k: j[k] for k in ("spot_id", "name", "grade", "reasons", "warnings", "wave_max_m", "wind_max_ms")}
                  for j in new],
        "candidates": [j["spot_id"] for j in candidates]})
    return {"judgments": judgments, "candidates": candidates, "excluded": excluded,
            "_end_payload": {"region": region, "candidates": len(candidates), "excluded": len(excluded)}}


# ---------- places ----------
@traced("places")
def places(state):
    top = state["candidates"][0]
    tasks = [{"tool": "search_places", "args": {"spot_id": top["spot_id"], "category": kind,
                                                "size": PLACES_PER_KIND}}
             for kind in state["conditions"].get("wants_places", [])]
    update = _execute(state, tasks)
    update["fatal_error"] = None  # 보조 정보 실패는 추천 자체를 막지 않는다
    update["_end_payload"] = {"spot_id": top["spot_id"], "kinds": [t["args"]["category"] for t in tasks]}
    return update


# ---------- replan ----------
@traced("replan")
def replan(state):
    nxt = untried_regions(state)[0]
    count = state.get("replan_count", 0) + 1
    reason = "조건에 맞는 후보가 없어 다음 지역을 확인합니다."
    bus.emit(state["session_id"], bus.REPLAN, {"count": count, "reason": reason, "next_region": nxt,
                                               "tried": state["tried_regions"]})
    return {"replan_count": count, "task_queue": build_tasks(state["conditions"], nxt),
            "tried_regions": list(state["tried_regions"]) + [nxt],
            "_end_payload": {"count": count, "next_region": nxt}}


# ---------- 분기 규칙 ----------
def route_after_judge(state):
    if state["candidates"]:
        return "places" if state["conditions"].get("wants_places") else "respond"
    if state.get("replan_count", 0) < config.MAX_REPLAN and untried_regions(state):
        return "replan"
    return "respond"