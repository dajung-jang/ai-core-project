"""계획 저장 흐름 테스트 (LLM·Tool은 가짜, 임시 DB): python -m scripts.test_save"""
import json
import os
import tempfile

import config
config.DB_PATH = os.path.join(tempfile.mkdtemp(), "test.db")

from agent import graph, llm
from events import bus
from spots import SPOTS
from store import db
from tools.base import TOOL_REGISTRY, ok

db.init_db()
events = []
bus.subscribe(events.append)


def fake(intent, conds=None, pick=None):
    payload = {"intent": intent, "reason": "테스트", "pick": pick, "conditions": conds or {}}
    llm.chat = lambda messages, **kw: json.dumps(payload, ensure_ascii=False)


def wave(region, date, start_time=None, end_time=None):
    return ok({"region": region, "date": date, "window": {}, "spots": [
        {"spot_id": s["id"], "name": s["name"], "max_wave_height_m": 0.45} for s in SPOTS if s["region"] == region]})


def beach(spot_ids, date, start_time=None, end_time=None):
    by = {s["id"]: s for s in SPOTS}
    return ok({"date": date, "window": {}, "spots": [
        {"spot_id": i, "name": by[i]["name"], "max_wind_speed_ms": 3.0} for i in spot_ids]})


TOOL_REGISTRY["get_wave_forecast"]["func"] = wave
TOOL_REGISTRY["get_beach_weather"]["func"] = beach
REQ = {"date": "2026-11-21", "start_time": "09:00", "end_time": "11:00", "region": "양양", "level": "초보"}

# 추천 전에 저장 요청 -> 안내
fake("save_plan")
f = graph.run_turn("S", "저장해줘")
assert "추천 결과가 아직 없어요" in f["answer"] and db.list_plans() == []

# 추천 -> 번호 없이 저장 요청(후보 3개) -> 되묻기
fake("plan_request", REQ)
f = graph.run_turn("S", "토요일 양양 초보 9시부터 11시")
assert len(f["candidates"]) == 3
fake("save_plan")
f = graph.run_turn("S", "저장해줘")
assert "어느 곳을 저장할까요" in f["answer"] and db.list_plans() == []

# 번호로 저장
fake("save_plan", pick="2")
f = graph.run_turn("S", "2번 저장")
p = db.list_plans()
assert len(p) == 1 and p[0]["date"] == "2026-11-21" and (p[0]["start_time"], p[0]["end_time"]) == ("09:00", "11:00")
assert p[0]["spot_id"] == f["save_target"]["spot_id"] and "저장했어요" in f["answer"] and "겹치는" not in f["answer"]
assert "created_at" in p[0] and p[0]["created_at"]

# 이름으로 같은 시간 또 저장 -> 저장은 되고 겹침 안내
fake("save_plan", pick="죽도")
f = graph.run_turn("S", "죽도로 저장")
assert len(db.list_plans()) == 2 and "겹치는" in f["answer"] and f"#{p[0]['id']}" in f["answer"]

# 저장 턴이 '직전 추천'을 덮어쓰지 않는다 + 이벤트 기록
assert graph._sessions["S"]["last"]["candidates"]
saved = [e for e in events if e["type"] == "plan_saved"]
assert len(saved) == 2 and saved[1]["payload"]["overlap_ids"] == [p[0]["id"]]

# 이름이 모호하면 되묻기
fake("save_plan", pick="양양")
f = graph.run_turn("S", "양양 저장")
assert "어느 곳을 저장할까요" in f["answer"] and len(db.list_plans()) == 2
print("모든 테스트 통과")