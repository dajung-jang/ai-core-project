"""터미널에서 Agent를 실제 LLM·실제 API로 돌려 보는 도구: python -m scripts.chat_cli

명령: /log (이번 세션 실행 로그 보기), /reset (새 세션), /quit
"""
import uuid

from agent.graph import reset_session, run_turn
from logging_agent import collector
from store import db


def show_trace(final):
    print("\n[실행 기록]")
    print(f"  의도: {final.get('intent')} ({final.get('intent_reason')})")
    print(f"  조건: {final.get('conditions')}")
    print(f"  시도한 지역: {final.get('tried_regions')}  재계획: {final.get('replan_count')}회")
    for i, t in enumerate(final.get("tool_log", []), 1):
        mark = "OK " if t["ok"] else "FAIL"
        extra = "캐시" if t["cached"] else f"{t['elapsed_ms']}ms"
        err = f" {t['error_code']}" if t["error_code"] else ""
        print(f"  {i}. [{mark}] {t['tool']} (재계획 {t['replan_count']}회차, {extra}){err}")


def show_log(session_id):
    events = db.get_session_events(session_id)
    print(f"\n[저장된 이벤트 {len(events)}개]")
    for e in events:
        p = e["payload"]
        brief = p.get("step") or p.get("tool") or p.get("next_region") or ""
        print(f"  #{e['seq']:>2} {e['type']:<14} {brief}")


def main():
    collector.start()
    session_id = "cli-" + uuid.uuid4().hex[:8]
    print(f"서핑 플래너 (세션 {session_id}). /log, /reset, /quit")
    while True:
        try:
            text = input("\n나> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text == "/quit":
            break
        if text == "/log":
            show_log(session_id)
            continue
        if text == "/reset":
            reset_session(session_id)
            session_id = "cli-" + uuid.uuid4().hex[:8]
            print(f"새 세션: {session_id}")
            continue
        final = run_turn(session_id, text)
        print("\n" + final["answer"])
        show_trace(final)


if __name__ == "__main__":
    main()