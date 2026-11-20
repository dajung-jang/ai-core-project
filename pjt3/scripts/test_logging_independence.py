"""로깅 Agent가 없거나 저장에 실패해도 메인 Agent가 정상 응답하는지 확인: python -m scripts.test_logging_independence"""
import json
import os
import tempfile

import config
config.DB_PATH = os.path.join(tempfile.mkdtemp(), "test.db")

from agent import graph, llm
from events import bus
from logging_agent import collector
from spots import SPOTS
from store import db
from tools.base import TOOL_REGISTRY, ok


def fake_llm():
    payload = {"intent": "plan_request", "reason": "테스트",
               "conditions": {"date": "2026-11-21", "region": "부산", "level": "초보"}}
    llm.chat = lambda messages, **kw: json.dumps(payload, ensure_ascii=False)


def wave(region, date, start_time=None, end_time=None):
    return ok({"region": region, "date": date, "window": {"start": "06:00", "end": "12:00"},
               "spots": [{"spot_id": s["id"], "name": s["name"], "max_wave_height_m": 0.4}
                         for s in SPOTS if s["region"] == region]})


def beach(spot_ids, date, start_time=None, end_time=None):
    return ok({"date": date, "window": {"start": "06:00", "end": "12:00"}, "spots": [
        {"spot_id": i, "name": i, "max_wind_speed_ms": 3.0, "observed": {"wave_height_m": 0.4, "water_temp_c": 14.0}}
        for i in spot_ids]})


import agent.nodes  # noqa: F401  (Tool 등록 뒤에 가짜로 교체)
TOOL_REGISTRY["get_wave_forecast"]["func"] = wave
TOOL_REGISTRY["get_beach_weather"]["func"] = beach
fake_llm()

# 1) 구독자가 하나도 없는 상태 (로깅 Agent 미연결)
bus.clear_subscribers()
final = graph.run_turn("ind-1", "토요일 오전 부산 초보")
assert final["answer"] and final["candidates"], "로깅 Agent 없이 응답해야 한다"
print("[통과] 로깅 Agent 미연결 상태에서 정상 응답")

# 2) 로깅 Agent는 연결했지만 저장이 항상 실패하는 상태
collector._started = False
collector.start()
def boom(event):
    raise RuntimeError("저장 실패(시험용)")
db.append_event = boom
final = graph.run_turn("ind-2", "토요일 오전 부산 초보")
assert final["answer"] and final["candidates"], "로그 저장이 실패해도 응답해야 한다"
print("[통과] 로그 저장 실패 상태에서 정상 응답")
print("모든 테스트 통과")