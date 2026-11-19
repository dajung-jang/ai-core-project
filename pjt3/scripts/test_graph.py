"""전체 흐름 테스트 (LLM·Tool은 가짜): python -m scripts.test_graph"""
import json

import config
from agent import graph, llm
from events import bus
from spots import SPOTS
from tools.base import TOOL_REGISTRY, fail, ok

events = []
bus.subscribe(events.append)
calls = {"wave": [], "beach": [], "places": []}
WAVE, WIND = {}, {}


def fake_llm(conds, intent="plan_request"):
    payload = {"intent": intent, "reason": "테스트", "conditions": conds}
    llm.chat = lambda messages, **kw: json.dumps(payload, ensure_ascii=False)


def wave(region, date, start_time=None, end_time=None):
    calls["wave"].append(region)
    return ok({"region": region, "date": date, "window": {"start": "06:00", "end": end_time},
               "spots": [{"spot_id": s["id"], "name": s["name"], "max_wave_height_m": WAVE[region]}
                         for s in SPOTS if s["region"] == region]})


def beach(spot_ids, date, start_time=None, end_time=None):
    calls["beach"].append(tuple(spot_ids))
    by = {s["id"]: s for s in SPOTS}
    return ok({"date": date, "window": {"start": "06:00", "end": end_time}, "spots": [
        {"spot_id": i, "name": by[i]["name"], "max_wind_speed_ms": WIND[by[i]["region"]],
         "observed": {"wave_height_m": 0.4, "water_temp_c": 14.0}} for i in spot_ids]})


def places(spot_id, category, size=None):
    calls["places"].append((spot_id, category))
    return ok({"spot_id": spot_id, "category": category, "places": [
        {"name": "테스트샵", "address": "강원 양양군", "distance_m": 300, "phone": None,
         "category_name": "x", "place_url": "u"}]})


def reset(w, wi):
    for k in calls: calls[k].clear()
    WAVE.clear(); WAVE.update(w); WIND.clear(); WIND.update(wi)
    TOOL_REGISTRY["get_wave_forecast"]["func"] = wave
    TOOL_REGISTRY["get_beach_weather"]["func"] = beach
    TOOL_REGISTRY["search_places"]["func"] = places


REQ1 = {"date": "2026-11-21", "end_by": "14:00", "region": "양양", "level": "초보"}

# A) 양양 부적합 -> 재계획 1회로 포항에서 후보
reset({"양양": 0.82, "포항": 0.45, "부산": 0.9, "제주": 0.9}, {"양양": 6.7, "포항": 3.0, "부산": 7, "제주": 7})
fake_llm(REQ1)
f = graph.run_turn("A", "토요일 양양 초보 2시 전엔 나와야 해")
assert f["replan_count"] == 1 and f["tried_regions"] == ["양양", "포항"]
assert [j["region"] for j in f["candidates"]] == ["포항", "포항"] and f["candidates"][0]["grade"] == "적합"
a = f["answer"]
for word in ("포항", "넓혀", "12:00", "초보 기준", "제외한 곳", "양양 죽도", "참고 정보", "출처", "4/3mm"):
    assert word in a, word
assert [l["replan_count"] for l in f["tool_log"]] == [0, 0, 1, 1]       # 재계획 지점이 로그에 구분된다
ev = [e for e in events if e["session_id"] == "A"]
assert [e["payload"]["count"] for e in ev if e["type"] == "replan"] == [1]
assert [e["seq"] for e in ev] == list(range(1, len(ev) + 1))

# B) 전부 부적합 -> 3회 재계획 후 사유와 함께 종료
reset({r: 0.9 for r in ("양양", "포항", "부산", "제주")}, {r: 7 for r in ("양양", "포항", "부산", "제주")})
fake_llm(REQ1)
f = graph.run_turn("B", "토요일 양양")
assert f["replan_count"] == config.MAX_REPLAN and len(f["tried_regions"]) == 4 and not f["candidates"]
assert "조정" in f["answer"] and "3회" in f["answer"]
assert len(f["excluded"]) == 9 and "제외한 곳" in f["answer"]

# C) 숙소 요청 -> 1순위 스팟 주변 조회
reset({"양양": 0.45, "포항": 0.9, "부산": 0.9, "제주": 0.9}, {"양양": 3, "포항": 7, "부산": 7, "제주": 7})
fake_llm({**REQ1, "wants_places": ["숙소"]})
f = graph.run_turn("C", "양양 숙소도")
assert f["replan_count"] == 0 and calls["places"] and calls["places"][0][1] == "숙소"
assert "테스트샵" in f["answer"]

# D) 키 누락 -> 재계획 없이 설정 안내
reset({}, {})
TOOL_REGISTRY["get_wave_forecast"]["func"] = lambda **k: fail("MISSING_KEY", "파고 예보 API 키가 설정되지 않았습니다.")
fake_llm(REQ1)
f = graph.run_turn("D", "x")
assert f["replan_count"] == 0 and ".env" in f["answer"] and not f["candidates"]

# E) 되묻기는 Tool 없이 끝난다
reset({}, {})
fake_llm({"level": "초보"}, "need_info")
f = graph.run_turn("E", "서핑하고 싶어")
assert "날짜" in f["answer"] and not calls["wave"]

# F) 같은 세션 후속 요청: 포항만 바꾸고, 이미 받은 결과는 재사용
reset({"양양": 0.82, "포항": 0.45, "부산": 0.9, "제주": 0.9}, {"양양": 6.7, "포항": 3.0, "부산": 7, "제주": 7})
fake_llm(REQ1)
graph.run_turn("F", "토요일 양양")
n = len(calls["wave"])                      # 양양, 포항
fake_llm({"region": "포항"}, "modify_request")
f = graph.run_turn("F", "포항은?")
assert f["conditions"]["date"] == "2026-11-21" and f["changed_conditions"] == ["region"]
assert len(calls["wave"]) == n and f["tool_log"][0]["cached"]          # 포항 결과 재사용, 재호출 없음

# G) 한 스팟만 해변 날씨 실패 -> 그 스팟만 판정 불가로 제외
reset({"양양": 0.45, "포항": 0.9, "부산": 0.9, "제주": 0.9}, {"양양": 3, "포항": 7, "부산": 7, "제주": 7})
def beach_partial(spot_ids, date, start_time=None, end_time=None):
    r = beach(spot_ids, date, start_time, end_time)
    r["data"]["spots"][0] = {"spot_id": spot_ids[0], "name": "양양 죽도",
                             "error": {"code": "NO_DATA", "message": "해변 예보가 없습니다."}}
    return r
TOOL_REGISTRY["get_beach_weather"]["func"] = beach_partial
fake_llm(REQ1)
f = graph.run_turn("G", "x")
assert [j["spot_id"] for j in f["candidates"]] == ["yy_ingu", "yy_gisamun"]
assert f["excluded"][0]["grade"] == "판정 불가" and "해변 예보가 없습니다" in f["answer"]

print("모든 테스트 통과")