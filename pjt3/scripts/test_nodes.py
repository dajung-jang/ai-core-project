"""analyze/plan/work 테스트 (LLM·Tool은 가짜로 대체): python -m scripts.test_nodes"""
import json

from agent import llm, nodes
from agent.state import new_state
from events import bus
from spots import SPOTS
from tools.base import TOOL_REGISTRY, fail, ok

events = []
bus.subscribe(events.append)


def fake_llm(payload):
    llm.chat = lambda messages, **kw: payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)


# 1) 요청 1: 토요일 양양 초보, 14시까지
fake_llm({"intent": "plan_request", "reason": "서핑 장소 문의",
          "conditions": {"date": "2026-11-21", "end_by": "14:00", "region": "양양", "level": "초보",
                         "start_time": "25:99", "wants_places": ["숙소", "점집"]}})
s = new_state("t1", "토요일 양양 초보 2시 전엔 나와야 해")
s.update(nodes.analyze(s))
c = s["conditions"]
assert s["intent"] == "plan_request" and not s.get("answer")
assert c["start_time"] is None and c["wants_places"] == ["숙소"]       # 잘못된 값은 버린다
s.update(nodes.plan(s))
t = s["task_queue"]
assert t[0]["args"] == {"region": "양양", "date": "2026-11-21", "end_time": "14:00"}
assert t[1]["args"]["spot_ids"] == [x["id"] for x in SPOTS if x["region"] == "양양"]

# 1-2) 오전(06~12) + 14시 종료 제한 -> 14시까지 본다
c9 = dict(c, start_time="06:00", end_time="12:00", end_by="14:00")
assert nodes.build_tasks(c9, "양양")[0]["args"]["end_time"] == "14:00"
assert nodes.build_tasks(dict(c9, end_by="10:00"), "양양")[0]["args"]["end_time"] == "12:00"


# 2) 날짜 없음 -> 되묻기, 조건은 보존
fake_llm({"intent": "plan_request", "reason": "x", "conditions": {"level": "초보", "region": "제주"}})
s2 = new_state("t2", "제주에서 초보 서핑")
s2.update(nodes.analyze(s2))
assert s2["intent"] == "need_info" and "날짜" in s2["answer"] and s2["conditions"]["region"] == "제주"

# 3) 중급 -> 안내, 범위 밖, 깨진 JSON
fake_llm({"intent": "plan_request", "reason": "x", "conditions": {"date": "2026-11-21", "level": "중급"}})
s3 = new_state("t3", "중급인데"); s3.update(nodes.analyze(s3))
assert s3["intent"] == "need_info" and "초보 기준" in s3["answer"]
fake_llm({"intent": "out_of_scope", "reason": "날씨 수다", "conditions": {}})
s4 = new_state("t4", "점심 뭐 먹지"); s4.update(nodes.analyze(s4)); assert "서핑 계획" in s4["answer"]
fake_llm("죄송합니다 모르겠어요")
s5 = new_state("t5", "???"); s5.update(nodes.analyze(s5)); assert s5["intent"] == "need_info" and s5["answer"]

# 4) "다른 지역으로" -> 바뀐 항목만 갱신
fake_llm({"intent": "modify_request", "reason": "지역 변경", "conditions": {"region": "포항"}})
s6 = new_state("t6", "포항은?", conditions=c); s6.update(nodes.analyze(s6))
assert s6["changed_conditions"] == ["region"] and s6["conditions"]["date"] == "2026-11-21"
assert s6["intent"] == "modify_request"

# 5) LLM 장애
def boom(messages, **kw): raise TimeoutError()
llm.chat = boom
s7 = new_state("t7", "x"); s7.update(nodes.analyze(s7)); assert s7["fatal_error"]["code"] == "LLM_ERROR"

# 6) work: 호출, 캐시 재사용, 재시도, 치명 오류
calls = {"wave": 0, "beach": 0}
def wave(region, date, start_time=None, end_time=None):
    calls["wave"] += 1
    return ok({"region": region, "date": date, "window": {"start": "06:00", "end": end_time},
               "spots": [{"spot_id": "yy_jukdo", "name": "양양 죽도", "max_wave_height_m": 0.82}]})
flaky = {"n": 0}
def beach(spot_ids, date, start_time=None, end_time=None):
    calls["beach"] += 1; flaky["n"] += 1
    if flaky["n"] == 1:
        return fail("HTTP_ERROR", "일시 오류")
    return ok({"date": date, "window": {"start": "06:00", "end": end_time}, "spots": [
        {"spot_id": "yy_jukdo", "name": "양양 죽도", "max_wind_speed_ms": 6.7,
         "observed": {"wave_height_m": 0.3, "water_temp_c": 14.0}}]})
TOOL_REGISTRY["get_wave_forecast"]["func"] = wave
TOOL_REGISTRY["get_beach_weather"]["func"] = beach
s.update(nodes.work(s))
assert calls == {"wave": 1, "beach": 2}                      # beach는 1회 재시도
assert all(e["ok"] for e in s["tool_log"]) and s["fatal_error"] is None
assert s["tool_cache"][next(k for k in s["tool_cache"] if "beach" in k)]["summary"]["spots"]["yy_jukdo"]["max_wind_ms"] == 6.7
s["task_queue"] = nodes.build_tasks(s["conditions"], "양양")  # 재계획 상황: 같은 호출
s.update(nodes.work(s))
assert calls == {"wave": 1, "beach": 2} and s["tool_log"][-1]["cached"]

TOOL_REGISTRY["get_wave_forecast"]["func"] = lambda **k: fail("MISSING_KEY", "키 없음")
s8 = new_state("t8", "x", conditions=c); s8["task_queue"] = nodes.build_tasks(c, "양양")
s8.update(nodes.work(s8))
assert s8["fatal_error"]["code"] == "MISSING_KEY" and len(s8["tool_log"]) == 1   # 즉시 중단

types = {e["type"] for e in events}
assert {"step_start", "step_end", "tool_request", "tool_response", "error"} <= types
ends = [e for e in events if e["type"] == "step_end" and e["payload"]["step"] == "analyze" and e["session_id"] == "t1"]
assert ends[0]["payload"]["intent"] == "plan_request"
print("모든 테스트 통과")