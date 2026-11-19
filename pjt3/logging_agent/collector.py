"""로깅 Agent의 수집기: 이벤트를 구독해 받는 즉시 세션별로 덧붙여 저장한다 (F3013).
LLM을 쓰지 않고, 발생한 사실을 가공 없이 그대로 남긴다. 저장에 실패해도 대화는 계속된다."""
from events import bus
from store import db

_started = False


def _on_event(event):
    try:
        db.append_event(event)
    except Exception:
        pass  # 저장 실패가 대화를 막지 않는다


def start():
    """한 번만 구독한다 (여러 번 불러도 안전)."""
    global _started
    if not _started:
        db.init_db()
        bus.subscribe(_on_event)
        _started = True