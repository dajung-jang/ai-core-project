"""Agent 단계(노드): analyze(LLM) -> plan(규칙) -> work(Tool 호출)"""
import functools
import json
import re
import time
from datetime import datetime, timedelta, timezone

from agent import llm
from agent.state import cache_key, merge_conditions, resolve_pick
from events import bus
from spots import SPOTS
from tools.base import NON_RETRYABLE, TOOL_REGISTRY, ErrorCode
import tools.beach, tools.places, tools.wave  # noqa: F401  (import 하면 TOOL_REGISTRY에 등록된다)

KST = timezone(timedelta(hours=9))
WEEKDAYS = "월화수목금토일"
REGIONS = sorted({s["region"] for s in SPOTS})
LEVELS = ("초보", "중급", "상급")
PLACE_KINDS = ("서핑샵", "숙소", "맛집")
INTENTS = ("plan_request", "modify_request", "save_plan", "need_info", "out_of_scope")
DEFAULT_REGION = "양양"
RETRY_ONCE = {ErrorCode.HTTP_ERROR, ErrorCode.PARSE_ERROR, ErrorCode.UNKNOWN}  # 같은 인자로 1회만 재시도
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

ANALYZE_SYSTEM = """너는 서핑 플래너의 요청 분석기다. 오늘은 {today}({weekday}요일)이다.
사용자 메시지와 지금까지 파악된 조건을 보고 JSON 하나만 출력한다. 설명은 쓰지 않는다.

{{"intent": "...", "reason": "한 문장", "pick": null, "conditions": {{...}}}}

intent:
- plan_request: 서핑 가능 여부·장소를 새로 묻는 요청
- modify_request: 앞선 요청의 조건(날짜·지역·시각 등)만 바꾸는 요청
- save_plan: 직전에 추천한 장소를 계획으로 저장해 달라는 요청 (pick에 번호나 장소 이름, 말하지 않았으면 null)
- need_info: 서핑 계획 요청이지만 판단에 필요한 정보가 전혀 없음
- out_of_scope: 서핑 계획과 무관한 요청

conditions (사용자가 이번 메시지에서 말한 것만 채우고, 말하지 않은 것은 null. 절대 짐작해서 채우지 않는다):
- date: YYYY-MM-DD (상대 날짜는 오늘 기준으로 계산)
- start_time, end_time: HH:MM. 사용자가 시각이나 시간대를 말한 경우만 (오전=06:00~12:00, 오후=12:00~18:00)
- end_by: '몇 시까지 끝내야/나와야 한다' 같은 종료 제한 HH:MM
- region: {regions} 중 하나
- level: 초보 / 중급 / 상급
- wants_places: 숙소, 서핑샵, 맛집 중 사용자가 알려 달라고 한 것의 목록 (없으면 [])"""


# ---------- 공통 ----------
def traced(step):
    """단계의 시작과 종료를 이벤트로 발행하고, 실패해도 Agent가 멈추지 않게 한다."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(state):
            sid = state["session_id"]
            bus.emit(sid, bus.STEP_START, {"step": step})
            t0 = time.perf_counter()
            try:
                update = fn(state) or {}
            except Exception as e:
                bus.emit(sid, bus.ERROR, {"step": step, "error": type(e).__name__})
                update = {"fatal_error": {"code": ErrorCode.UNKNOWN,
                                          "message": f"{step} 단계에서 오류가 발생했습니다."}}
            extra = update.pop("_end_payload", {})
            bus.emit(sid, bus.STEP_END, {"step": step,
                                         "elapsed_ms": round((time.perf_counter() - t0) * 1000), **extra})
            return update
        return wrapper
    return deco


def _parse_json(text):
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        return json.loads(text[a:b + 1])
    except ValueError:
        return None


def _clean_conditions(raw):
    """LLM이 준 조건에서 형식이 맞는 값만 남긴다."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    d = raw.get("date")
    try:
        datetime.strptime(d, "%Y-%m-%d")
        out["date"] = d
    except (ValueError, TypeError):
        out["date"] = None
    for k in ("start_time", "end_time", "end_by"):
        v = raw.get(k)
        out[k] = v if isinstance(v, str) and TIME_RE.match(v) else None
    out["region"] = raw.get("region") if raw.get("region") in REGIONS else None
    out["level"] = raw.get("level") if raw.get("level") in LEVELS else None
    wp = raw.get("wants_places")
    out["wants_places"] = [p for p in wp if p in PLACE_KINDS] if isinstance(wp, list) else []
    return out


# ---------- 1. analyze (LLM) ----------
@traced("analyze")
def analyze(state):
    sid = state["session_id"]
    now = datetime.now(KST)
    system = ANALYZE_SYSTEM.format(today=now.strftime("%Y-%m-%d"), weekday=WEEKDAYS[now.weekday()],
                                   regions=", ".join(REGIONS))
    user = (f"지금까지 파악된 조건: {json.dumps(state['conditions'], ensure_ascii=False)}\n"
            f"사용자 메시지: {state['user_message']}")
    messages = [{"role": "system", "content": system}] + state.get("history", [])[-6:] \
        + [{"role": "user", "content": user}]
    try:
        text = llm.chat(messages)
    except Exception as e:
        bus.emit(sid, bus.ERROR, {"step": "analyze", "error": type(e).__name__})
        return {"fatal_error": {"code": "LLM_ERROR", "message": "요청을 분석하지 못했습니다. 잠시 후 다시 시도해 주세요."},
                "_end_payload": {"intent": None, "reason": "LLM 호출 실패"}}

    parsed = _parse_json(text) or {}
    intent = parsed.get("intent") if parsed.get("intent") in INTENTS else "need_info"
    reason = str(parsed.get("reason") or "")[:200]
    conds, changed = merge_conditions(state["conditions"], _clean_conditions(parsed.get("conditions")))

    update = {"intent": intent, "intent_reason": reason, "conditions": conds, "changed_conditions": changed}
    if "date" in changed:
        update["tool_cache"] = {}  # 날짜가 바뀌면 이전 Tool 결과는 쓸 일이 없다

    if intent == "save_plan":
        cands = state.get("last_candidates") or []
        if not cands:
            update["answer"] = "저장할 추천 결과가 아직 없어요. 먼저 서핑 장소를 찾아볼까요?"
            update["intent"] = "need_info"
        else:
            target, ask = resolve_pick(cands, parsed.get("pick"))
            if target:
                update["save_target"] = target
            else:
                update["answer"] = ask
                update["intent"] = "need_info"
    elif intent == "out_of_scope":
        update["answer"] = "서핑 계획(파도·바람 확인, 스팟 추천)과 관련된 요청만 도와드릴 수 있어요."
    elif intent in ("plan_request", "modify_request", "need_info"):
        missing = []
        if not conds["date"]:
            missing.append("서핑하려는 날짜")
        if not conds["level"]:
            missing.append("서핑 경험 수준(초보/중급/상급)")
        if conds["level"] and conds["level"] != "초보":
            update["answer"] = ("현재는 초보 기준(파고 0.3~0.8m, 풍속 5m/s 이하)만 판단할 수 있어요. "
                                "초보 기준으로 확인해 볼까요?")
            update["intent"] = "need_info"
        elif missing:
            update["answer"] = "계획을 세우려면 " + ", ".join(missing) + "을(를) 알려 주세요."
            update["intent"] = "need_info"
        else:
            update["intent"] = "plan_request" if intent == "need_info" else intent
    update["_end_payload"] = {"intent": update["intent"], "reason": reason,
                              "conditions": conds, "changed": changed}
    return update


# ---------- 2. plan (규칙) ----------
def effective_end(conditions):
    """판단할 시간대의 끝. 종료 제한(end_by)이 있으면 물에서 나오는 시각까지 봐야 하므로 둘 중 늦은 쪽을 쓴다."""
    ends = [t for t in (conditions.get("end_time"), conditions.get("end_by")) if t]
    return max(ends) if ends else None


def build_tasks(conditions, region):
    """조건과 지역으로 Tool 작업 목록을 만든다. 시각은 사용자가 말한 것만 넣는다."""
    window = {}
    if conditions.get("start_time"):
        window["start_time"] = conditions["start_time"]
    end = effective_end(conditions)
    if end:
        window["end_time"] = end
    spot_ids = [s["id"] for s in SPOTS if s["region"] == region]
    return [
        {"tool": "get_wave_forecast", "args": {"region": region, "date": conditions["date"], **window}},
        {"tool": "get_beach_weather", "args": {"spot_ids": spot_ids, "date": conditions["date"], **window}},
    ]


@traced("plan")
def plan(state):
    c = state["conditions"]
    region = c.get("region") or DEFAULT_REGION
    tasks = build_tasks(c, region)
    return {"task_queue": tasks, "tried_regions": list(state.get("tried_regions", [])) + [region],
            "_end_payload": {"region": region, "region_assumed": not c.get("region"),
                             "tasks": [t["tool"] for t in tasks]}}


# ---------- 3. work (Tool 호출) ----------
def _summarize(tool, data):
    """원본 응답 대신 판단에 필요한 값만 남긴다 (대화 맥락·로그에 원본을 쌓지 않는다)."""
    if tool == "get_wave_forecast":
        return {"region": data["region"], "date": data["date"], "window": data["window"],
                "spots": {s["spot_id"]: {"name": s["name"], "max_wave_m": s["max_wave_height_m"]}
                          for s in data["spots"]}}
    if tool == "get_beach_weather":
        spots = {}
        for s in data["spots"]:
            obs = s.get("observed") or {}
            err = s.get("error") or {}
            spots[s["spot_id"]] = {"name": s["name"], "max_wind_ms": s.get("max_wind_speed_ms"),
                                   "observed_wave_m": obs.get("wave_height_m"),
                                   "observed_water_c": obs.get("water_temp_c"),
                                   "error_code": err.get("code"), "error_message": err.get("message")}
        return {"date": data["date"], "window": data["window"], "spots": spots}
    if tool == "search_places":
        return {"spot_id": data["spot_id"], "category": data["category"],
                "places": [{"name": p["name"], "address": p["address"], "distance_m": p["distance_m"]}
                           for p in data["places"]]}
    return {}


def _run_tool(sid, tool, args):
    """Tool을 부르고 (결과, 걸린 ms, 시도 횟수)를 돌려준다. 일시적 실패는 같은 인자로 1회만 재시도한다."""
    func = TOOL_REGISTRY[tool]["func"]
    result, ms = None, 0
    for attempt in (1, 2):
        bus.emit(sid, bus.TOOL_REQUEST, {"tool": tool, "args": args, "attempt": attempt})
        t0 = time.perf_counter()
        result = func(**args)
        ms = round((time.perf_counter() - t0) * 1000)
        payload = {"tool": tool, "ok": result["ok"], "elapsed_ms": ms, "attempt": attempt}
        payload["summary" if result["ok"] else "error"] = (
            _summarize(tool, result["data"]) if result["ok"] else result["error"])
        bus.emit(sid, bus.TOOL_RESPONSE, payload)
        if result["ok"] or result["error"]["code"] not in RETRY_ONCE:
            return result, ms, attempt
    return result, ms, 2


def _execute(state, tasks):
    """작업 목록을 순서대로 실행해 상태 갱신분을 돌려준다. 이미 받은 결과는 다시 부르지 않는다."""
    sid = state["session_id"]
    cache = dict(state.get("tool_cache", {}))
    log = list(state.get("tool_log", []))
    fatal = None
    for task in tasks:
        tool, args = task["tool"], task["args"]
        key = cache_key(tool, args)
        entry = {"tool": tool, "args": args, "replan_count": state.get("replan_count", 0)}
        if cache.get(key, {}).get("ok"):
            log.append({**entry, "ok": True, "cached": True, "elapsed_ms": 0, "error_code": None})
            bus.emit(sid, bus.TOOL_RESPONSE, {"tool": tool, "cached": True, "ok": True})
            continue
        result, ms, attempts = _run_tool(sid, tool, args)
        if result["ok"]:
            cache[key] = {"ok": True, "summary": _summarize(tool, result["data"])}
            log.append({**entry, "ok": True, "cached": False, "elapsed_ms": ms, "error_code": None})
        else:
            err = result["error"]
            cache[key] = {"ok": False, "error": err}
            log.append({**entry, "ok": False, "cached": False, "elapsed_ms": ms, "error_code": err["code"]})
            if err["code"] in NON_RETRYABLE:  # 키 누락·인증·입력 오류는 재계획해도 소용없다
                fatal = err
                break
    return {"tool_cache": cache, "tool_log": log, "fatal_error": fatal}


@traced("work")
def work(state):
    update = _execute(state, state["task_queue"])
    update["_end_payload"] = {"calls": len(state["task_queue"]), "fatal": bool(update["fatal_error"])}
    return update
