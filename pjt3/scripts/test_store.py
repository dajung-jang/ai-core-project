"""store/db.py, collector 테스트 (임시 DB 사용): python -m scripts.test_store"""
import os
import tempfile

import config
config.DB_PATH = os.path.join(tempfile.mkdtemp(), "test.db")

from events import bus
from logging_agent import collector
from store import db

collector.start(); collector.start()  # 두 번 불러도 한 번만 구독
bus.emit("s1", bus.STEP_START, {"step": "analyze"})
bus.emit("s1", bus.TOOL_REQUEST, {"tool": "get_wave_forecast"})
bus.emit("s1", bus.REPLAN, {"count": 1})
bus.emit("s2", bus.ERROR, {"code": "MISSING_KEY"})
ev = db.get_session_events("s1")
assert [e["seq"] for e in ev] == [1, 2, 3] and ev[1]["payload"]["tool"] == "get_wave_forecast"
ss = {s["session_id"]: s for s in db.list_sessions()}
assert ss["s1"]["event_count"] == 3 and ss["s1"]["replan_count"] == 1 and ss["s2"]["error_count"] == 1
assert db.delete_session("s1") == 3 and db.get_session_events("s1") == []

# 구독자가 망가져도 emit은 계속 동작
bus.subscribe(lambda e: 1 / 0)
assert bus.emit("s3", bus.STEP_END)["seq"] == 1

p1, ov = db.save_plan("yy_jukdo", "양양 죽도", "2026-11-21", "10:00", "12:00")
assert ov == []
p2, ov = db.save_plan("bs_songjeong", "부산 송정", "2026-11-21", "11:00", "13:00")
assert [o["id"] for o in ov] == [p1["id"]]                       # 겹쳐도 저장은 됨
p3, ov = db.save_plan("jj_jungmun", "제주 중문", "2026-11-21", "12:00", "14:00")
assert [o["id"] for o in ov] == [p2["id"]]                       # 12:00 맞닿음(p1)은 겹침 아님
assert len(db.list_plans()) == 3
u, ov = db.update_plan(p3["id"], date="2026-11-22")
assert u["date"] == "2026-11-22" and ov == [] and u["updated_at"]
assert db.update_plan(999, note="x")[0] is None
assert db.delete_plan(p1["id"]) and not db.delete_plan(p1["id"])
try:
    db.save_plan("x", "x", "2026-11-21", "12:00", "10:00"); assert False
except ValueError:
    pass
print("모든 테스트 통과")