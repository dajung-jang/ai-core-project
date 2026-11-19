"""이벤트 버스: 메인 Agent는 emit()만 호출하고, 누가 구독하는지 모른다 (F3012)"""
import itertools
import threading
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

# 이벤트 종류
STEP_START = "step_start"
STEP_END = "step_end"
TOOL_REQUEST = "tool_request"
TOOL_RESPONSE = "tool_response"
LLM_DECISION = "llm_decision"
JUDGE_RESULT = "judge_result"
REPLAN = "replan"
PLAN_SAVED = "plan_saved"
ERROR = "error"

_subscribers = []
_seq = {}
_lock = threading.Lock()


def subscribe(callback):
    """callback(event: dict) 를 등록한다."""
    _subscribers.append(callback)


def clear_subscribers():
    _subscribers.clear()


def emit(session_id, type_, payload=None):
    """이벤트를 만들어 구독자 모두에게 전달한다. 구독자가 실패해도 Agent는 계속 동작한다."""
    with _lock:
        counter = _seq.setdefault(session_id, itertools.count(1))
        seq = next(counter)
    event = {
        "session_id": session_id,
        "seq": seq,
        "ts": datetime.now(KST).isoformat(timespec="milliseconds"),
        "type": type_,
        "payload": payload or {},
    }
    for cb in list(_subscribers):
        try:
            cb(event)
        except Exception:
            pass  # 저장 실패가 대화를 막지 않도록 삼킨다
    return event