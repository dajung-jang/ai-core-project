"""API 요청·응답 형식 (F3017)"""
from typing import Any, Optional

from pydantic import BaseModel, Field

DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"


# ---------- 대화 ----------
class ChatRequest(BaseModel):
    session_id: Optional[str] = Field(None, pattern=r"^[A-Za-z0-9_-]{1,64}$",
                                      description="없으면 서버가 새로 만든다")
    message: str = Field(..., min_length=1, max_length=500)


class ToolCallOut(BaseModel):
    tool: str
    args: dict[str, Any]
    ok: bool
    cached: bool
    elapsed_ms: int
    error_code: Optional[str] = None
    replan_count: int  # 0이면 첫 계획, 1 이상이면 그 번째 재계획에서 호출


class EventOut(BaseModel):
    seq: int
    ts: str
    type: str
    payload: dict[str, Any]


class ErrorOut(BaseModel):
    code: str
    message: str


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    intent: Optional[str] = None
    intent_reason: Optional[str] = None
    conditions: dict[str, Any]
    replan_count: int
    tried_regions: list[str]
    tool_log: list[ToolCallOut]
    events: list[EventOut]  # 이번 요청에서 발생한 실행 단계·Tool 호출 이벤트(순서대로)
    error: Optional[ErrorOut] = None  # API 키 누락 등 치명 오류 (화면에 설정 안내를 띄운다)


# ---------- 계획 ----------
class PlanOut(BaseModel):
    id: int
    spot_id: str
    spot_name: str
    date: str
    start_time: str
    end_time: str
    note: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None


class PlanUpdate(BaseModel):
    date: Optional[str] = Field(None, pattern=DATE_PATTERN)
    start_time: Optional[str] = Field(None, pattern=TIME_PATTERN)
    end_time: Optional[str] = Field(None, pattern=TIME_PATTERN)
    note: Optional[str] = Field(None, max_length=300)


class PlanUpdateResult(BaseModel):
    plan: PlanOut
    overlaps: list[PlanOut]  # 같은 날 시간이 겹치는 다른 계획 (수정은 되어 있다)


# ---------- 실행 로그 ----------
class SessionSummary(BaseModel):
    session_id: str
    event_count: int
    started_at: str
    last_at: str
    error_count: int
    replan_count: int


class SessionDetail(BaseModel):
    session_id: str
    events: list[EventOut]


class DeleteResult(BaseModel):
    deleted: int


# ---------- 상태 ----------
class HealthOut(BaseModel):
    status: str
    keys: dict[str, bool]  # llm / beach / kakao 키가 설정되어 있는지
    missing_guide: list[str]