"""SQLite 저장소: 실행 로그(event_log)와 계획(plans)"""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

import config

KST = timezone(timedelta(hours=9))

SCHEMA = """
CREATE TABLE IF NOT EXISTS event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_event_session ON event_log(session_id, seq);
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spot_id TEXT NOT NULL,
    spot_name TEXT NOT NULL,
    date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);
"""


def _conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(_conn()) as c:
        c.executescript(SCHEMA)
        c.commit()


# ---------- 실행 로그: 추가 / 조회 / 삭제만 있고 수정은 없다 (F3013, F3014) ----------
def append_event(event):
    with closing(_conn()) as c:
        c.execute("INSERT INTO event_log(session_id, seq, ts, type, payload) VALUES (?,?,?,?,?)",
                  (event["session_id"], event["seq"], event["ts"], event["type"],
                   json.dumps(event.get("payload", {}), ensure_ascii=False)))
        c.commit()


def list_sessions():
    with closing(_conn()) as c:
        rows = c.execute(
            "SELECT session_id, COUNT(*) AS event_count, MIN(ts) AS started_at, MAX(ts) AS last_at, "
            "SUM(type='error') AS error_count, SUM(type='replan') AS replan_count "
            "FROM event_log GROUP BY session_id ORDER BY MIN(id) DESC").fetchall()
    return [dict(r) for r in rows]


def get_session_events(session_id):
    with closing(_conn()) as c:
        rows = c.execute("SELECT seq, ts, type, payload FROM event_log WHERE session_id=? ORDER BY seq, id",
                         (session_id,)).fetchall()
    return [{"seq": r["seq"], "ts": r["ts"], "type": r["type"], "payload": json.loads(r["payload"])}
            for r in rows]


def delete_session(session_id):
    with closing(_conn()) as c:
        n = c.execute("DELETE FROM event_log WHERE session_id=?", (session_id,)).rowcount
        c.commit()
    return n


# ---------- 계획 (F3015, F3016) ----------
def _overlaps(date, start, end, exclude_id=None):
    with closing(_conn()) as c:
        rows = c.execute("SELECT * FROM plans WHERE date=? AND start_time < ? AND end_time > ?",
                         (date, end, start)).fetchall()
    return [dict(r) for r in rows if r["id"] != exclude_id]


def _check(date, start, end):
    datetime.strptime(date, "%Y-%m-%d")
    datetime.strptime(start, "%H:%M")
    datetime.strptime(end, "%H:%M")
    if start >= end:
        raise ValueError("시작 시각이 종료 시각보다 빨라야 합니다.")


def save_plan(spot_id, spot_name, date, start_time, end_time, note=None):
    """저장은 항상 한다. 같은 날 시간이 겹치는 기존 계획이 있으면 함께 돌려준다."""
    _check(date, start_time, end_time)
    overlaps = _overlaps(date, start_time, end_time)
    with closing(_conn()) as c:
        cur = c.execute("INSERT INTO plans(spot_id, spot_name, date, start_time, end_time, note, created_at) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (spot_id, spot_name, date, start_time, end_time, note,
                         datetime.now(KST).isoformat(timespec="seconds")))
        c.commit()
        plan_id = cur.lastrowid
    return get_plan(plan_id), overlaps


def get_plan(plan_id):
    with closing(_conn()) as c:
        r = c.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
    return dict(r) if r else None


def list_plans():
    with closing(_conn()) as c:
        rows = c.execute("SELECT * FROM plans ORDER BY date, start_time, id").fetchall()
    return [dict(r) for r in rows]


def update_plan(plan_id, **fields):
    """date, start_time, end_time, note 만 수정할 수 있다. 없으면 None."""
    cur = get_plan(plan_id)
    if not cur:
        return None, []
    new = {k: fields.get(k) if fields.get(k) is not None else cur[k]
           for k in ("date", "start_time", "end_time", "note")}
    _check(new["date"], new["start_time"], new["end_time"])
    overlaps = _overlaps(new["date"], new["start_time"], new["end_time"], exclude_id=plan_id)
    with closing(_conn()) as c:
        c.execute("UPDATE plans SET date=?, start_time=?, end_time=?, note=?, updated_at=? WHERE id=?",
                  (new["date"], new["start_time"], new["end_time"], new["note"],
                   datetime.now(KST).isoformat(timespec="seconds"), plan_id))
        c.commit()
    return get_plan(plan_id), overlaps


def delete_plan(plan_id):
    with closing(_conn()) as c:
        n = c.execute("DELETE FROM plans WHERE id=?", (plan_id,)).rowcount
        c.commit()
    return n > 0