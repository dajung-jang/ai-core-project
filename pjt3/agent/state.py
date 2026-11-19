"""Agent 상태와 조건 갱신 규칙 (F3005, F3010)"""
import json
from typing import Optional, TypedDict

MAX_HISTORY_TURNS = 6  # 대화 맥락으로 보관할 최근 턴 수 (사용자 요청 + 응답 = 1턴)

# 사용자 조건 항목. 값이 None이면 '아직 모름'
CONDITION_KEYS = ("date", "start_time", "end_time", "region", "level", "end_by", "wants_places")


def empty_conditions():
    return {"date": None, "start_time": None, "end_time": None, "region": None,
            "level": None, "end_by": None, "wants_places": []}


def merge_conditions(old, new):
    """새로 추출된 값 중 None이 아닌 것만 덮어쓴다. 바뀐 항목 이름 목록도 함께 돌려준다."""
    merged = dict(old)
    changed = []
    for k in CONDITION_KEYS:
        v = (new or {}).get(k)
        if v in (None, "", []):
            continue
        if merged.get(k) != v:
            merged[k] = v
            changed.append(k)
    return merged, changed


class AgentState(TypedDict, total=False):
    session_id: str
    user_message: str
    history: list            # [{"role": "user"|"assistant", "content": str}] 최근 N턴
    intent: str              # plan_request | modify_request | need_info | out_of_scope
    intent_reason: str
    conditions: dict
    changed_conditions: list
    task_queue: list         # [{"tool": str, "args": dict}]
    tool_cache: dict         # {cache_key: 요약 결과} - 재계획 때 재사용
    tool_log: list           # 화면 표시용 Tool 호출 이력
    judgments: list
    candidates: list
    excluded: list
    tried_regions: list
    replan_count: int
    fatal_error: Optional[dict]
    answer: str
    last_candidates: list   # 직전 추천 결과 요약 (저장 요청에 쓴다)
    last_conditions: dict
    save_target: Optional[dict]


def cache_key(tool, args):
    return tool + ":" + json.dumps(args, sort_keys=True, ensure_ascii=False)


def new_state(session_id, user_message, history=None, conditions=None, tool_cache=None, last=None):
    """한 턴을 시작할 때의 초기 상태. 대화 맥락(history, conditions)은 이전 턴 것을 이어받는다."""
    return AgentState(
        session_id=session_id, user_message=user_message,
        history=(history or [])[-MAX_HISTORY_TURNS * 2:],
        conditions=dict(conditions) if conditions else empty_conditions(),
        changed_conditions=[], task_queue=[], tool_log=[],
        tool_cache={k: v for k, v in (tool_cache or {}).items() if v.get("ok")},  # 실패 결과는 이어받지 않는다
        judgments=[], candidates=[], excluded=[], tried_regions=[],
        replan_count=0, fatal_error=None, answer="",
        last_candidates=(last or {}).get("candidates", []), last_conditions=(last or {}).get("conditions"),
        save_target=None,
    )


def trim_history(history):
    return history[-MAX_HISTORY_TURNS * 2:]


def resolve_pick(candidates, pick):
    """'1', '송정' 같은 사용자 지정으로 저장할 후보를 고른다. (후보, 되묻는 문장)을 돌려준다."""
    if pick is not None and str(pick).strip():
        p = str(pick).strip()
        if p.isdigit() and 1 <= int(p) <= len(candidates):
            return candidates[int(p) - 1], None
        hits = [c for c in candidates if p in c["name"] or c["name"] in p]
        if len(hits) == 1:
            return hits[0], None
    elif len(candidates) == 1:
        return candidates[0], None
    lines = [f"{i}. {c['name']} ({c['grade']})" for i, c in enumerate(candidates, 1)]
    return None, "어느 곳을 저장할까요? 번호나 이름으로 알려 주세요.\n" + "\n".join(lines)