"""API 테스트 (LLM·Tool은 가짜, 임시 DB): python -m scripts.test_api"""
import json
import os
import tempfile

import config
config.DB_PATH = os.path.join(tempfile.mkdtemp(), "test.db")

from fastapi.testclient import TestClient

from agent import llm
from backend.main import app
from spots import SPOTS
from tools.base import TOOL_REGISTRY, fail, ok


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

with TestClient(app) as c:
    # 상태
    h = c.get("/api/health").json()
    assert h["status"] == "ok" and set(h["keys"]) == {"llm", "beach", "kakao"}

    # 대화: 입력 검증
    assert c.post("/api/chat", json={"message": ""}).status_code == 422
    assert c.post("/api/chat", json={"message": "x", "session_id": "../bad"}).status_code == 422

    # 대화: 되묻기(Tool 없음), 세션 id 발급
    fake("need_info", {"level": "초보"})
    r = c.post("/api/chat", json={"message": "서핑하고 싶어"}).json()
    assert "날짜" in r["answer"] and r["tool_log"] == [] and len(r["session_id"]) == 12 and r["error"] is None
    sid = r["session_id"]

    # 대화: 추천. 이번 턴의 이벤트·Tool 이력이 순서대로 온다
    fake("plan_request", REQ)
    r = c.post("/api/chat", json={"session_id": "api1", "message": "토요일 양양 초보"}).json()
    assert r["replan_count"] == 0 and len(r["tool_log"]) == 2 and "추천" in r["answer"]
    seqs = [e["seq"] for e in r["events"]]
    assert seqs == list(range(1, len(seqs) + 1)) and r["events"][0]["type"] == "step_start"
    assert r["tool_log"][0]["tool"] == "get_wave_forecast" and r["tool_log"][0]["replan_count"] == 0

    # 같은 세션 두 번째 요청: 이벤트는 새로 발생한 것만 온다
    fake("save_plan", pick="1")
    r2 = c.post("/api/chat", json={"session_id": "api1", "message": "1번 저장"}).json()
    assert "저장했어요" in r2["answer"] and r2["events"][0]["seq"] == seqs[-1] + 1

    # 계획 관리
    plans = c.get("/api/plans").json()
    assert len(plans) == 1 and plans[0]["start_time"] == "09:00"
    pid = plans[0]["id"]
    assert c.get(f"/api/plans/{pid}").json()["spot_id"] == plans[0]["spot_id"]
    assert c.get("/api/plans/999").status_code == 404

    fake("save_plan", pick="2")
    c.post("/api/chat", json={"session_id": "api1", "message": "2번도 저장"})
    p2 = [p for p in c.get("/api/plans").json() if p["id"] != pid][0]
    u = c.patch(f"/api/plans/{p2['id']}", json={"date": "2026-11-22"}).json()   # 겹침 해소
    assert u["plan"]["date"] == "2026-11-22" and u["overlaps"] == [] and u["plan"]["updated_at"]
    u = c.patch(f"/api/plans/{p2['id']}", json={"date": "2026-11-21", "start_time": "10:00"}).json()
    assert [o["id"] for o in u["overlaps"]] == [pid]                              # 겹침 알림
    assert c.patch(f"/api/plans/{pid}", json={}).status_code == 422
    assert c.patch(f"/api/plans/{pid}", json={"start_time": "25:00"}).status_code == 422
    assert c.patch(f"/api/plans/{pid}", json={"start_time": "12:00"}).status_code == 422   # 시작 > 종료
    assert c.patch("/api/plans/999", json={"note": "x"}).status_code == 404
    assert c.delete(f"/api/plans/{pid}").json() == {"deleted": 1}
    assert c.delete(f"/api/plans/{pid}").status_code == 404
    assert [p["id"] for p in c.get("/api/plans").json()] == [p2["id"]]            # 삭제가 목록에 반영

    # 실행 로그: 목록·상세·삭제, 수정 API는 없다
    sessions = {s["session_id"]: s for s in c.get("/api/logs").json()}
    assert "api1" in sessions and sessions["api1"]["event_count"] > 10
    d = c.get("/api/logs/api1").json()
    assert [e["seq"] for e in d["events"]] == list(range(1, len(d["events"]) + 1))
    assert c.put("/api/logs/api1", json={}).status_code == 405
    assert c.patch("/api/logs/api1", json={}).status_code == 405
    assert c.delete("/api/logs/api1").json()["deleted"] == len(d["events"])
    assert c.get("/api/logs/api1").status_code == 404 and c.delete("/api/logs/api1").status_code == 404

    # 키 누락: 응답의 error로 설정 안내가 온다
    TOOL_REGISTRY["get_wave_forecast"]["func"] = lambda **k: fail("MISSING_KEY", "파고 예보 API 키가 설정되지 않았습니다.")
    fake("plan_request", REQ)
    r = c.post("/api/chat", json={"session_id": "api2", "message": "x"}).json()
    assert r["error"]["code"] == "MISSING_KEY" and ".env" in r["answer"]

    # 예상 못 한 오류도 500 + 안내문으로 (내부 정보 노출 없음)
    import backend.main as m
    m.run_turn = lambda *a, **k: 1 / 0
    r = c.post("/api/chat", json={"message": "x"})
    assert r.status_code == 500 and "division" not in r.text
print("모든 테스트 통과")