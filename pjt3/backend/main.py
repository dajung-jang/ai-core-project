"""FastAPI 백엔드 (F3017): 대화 · 계획 관리 · 실행 로그 조회 API
실행: uvicorn backend.main:app --reload   (프로젝트 루트에서)
"""
import os
import threading
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

import config
from agent.graph import run_turn
from backend.schemas import (ChatRequest, ChatResponse, DeleteResult, HealthOut, PlanOut, PlanUpdate,
                             PlanUpdateResult, SessionDetail, SessionSummary)
from logging_agent import collector
from store import db

_locks = defaultdict(threading.Lock)  # 같은 세션의 요청은 한 번에 하나씩 처리한다


@asynccontextmanager
async def lifespan(app):
    collector.start()  # 로깅 Agent: DB 준비 + 이벤트 구독
    yield


app = FastAPI(title="서핑 플래너 API", lifespan=lifespan)

KEY_GUIDE = {
    "llm": ("GMS_KEY", "대화 분석에 쓰는 LLM 키(GMS_KEY)가 없어요. .env에 GMS_KEY, GMS_BASE_URL, LLM_MODEL을 넣어 주세요."),
    "beach": ("DATA_GO_KR_KEY_BEACH", "해변 날씨 키(DATA_GO_KR_KEY_BEACH)가 없어요. 공공데이터포털 인증키를 .env에 넣어 주세요."),
    "kakao": ("KAKAO_REST_API_KEY", "장소 검색 키(KAKAO_REST_API_KEY)가 없어요. 카카오 REST API 키를 .env에 넣어 주세요."),
}


# ---------- 상태 ----------
@app.get("/api/health", response_model=HealthOut)
def health():
    keys = {k: bool(getattr(config, attr, None)) for k, (attr, _) in KEY_GUIDE.items()}
    return HealthOut(status="ok", keys=keys,
                     missing_guide=[KEY_GUIDE[k][1] for k, present in keys.items() if not present])


# ---------- 대화 ----------
@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    session_id = req.session_id or uuid.uuid4().hex[:12]
    with _locks[session_id]:
        before = len(db.get_session_events(session_id))
        try:
            final = run_turn(session_id, req.message)
        except Exception:
            raise HTTPException(status_code=500, detail="요청을 처리하는 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요.")
        events = db.get_session_events(session_id)[before:]
    return ChatResponse(
        session_id=session_id, answer=final["answer"], intent=final.get("intent"),
        intent_reason=final.get("intent_reason"), conditions=final["conditions"],
        replan_count=final.get("replan_count", 0), tried_regions=final.get("tried_regions", []),
        tool_log=final.get("tool_log", []), events=events, error=final.get("fatal_error"))


# ---------- 계획 관리 ----------
@app.get("/api/plans", response_model=list[PlanOut])
def list_plans():
    return db.list_plans()


@app.get("/api/plans/{plan_id}", response_model=PlanOut)
def get_plan(plan_id: int):
    plan = db.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="계획을 찾을 수 없어요.")
    return plan


@app.patch("/api/plans/{plan_id}", response_model=PlanUpdateResult)
def update_plan(plan_id: int, body: PlanUpdate):
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=422, detail="수정할 값을 하나 이상 보내 주세요.")
    try:
        plan, overlaps = db.update_plan(plan_id, **fields)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if not plan:
        raise HTTPException(status_code=404, detail="계획을 찾을 수 없어요.")
    return PlanUpdateResult(plan=plan, overlaps=overlaps)


@app.delete("/api/plans/{plan_id}", response_model=DeleteResult)
def delete_plan(plan_id: int):
    if not db.delete_plan(plan_id):
        raise HTTPException(status_code=404, detail="계획을 찾을 수 없어요.")
    return DeleteResult(deleted=1)


# ---------- 실행 로그: 목록·상세·삭제만 제공하고 수정 API는 두지 않는다 (F3014) ----------
@app.get("/api/logs", response_model=list[SessionSummary])
def list_logs():
    return db.list_sessions()


@app.get("/api/logs/{session_id}", response_model=SessionDetail)
def get_log(session_id: str):
    events = db.get_session_events(session_id)
    if not events:
        raise HTTPException(status_code=404, detail="해당 세션의 실행 로그가 없어요.")
    return SessionDetail(session_id=session_id, events=events)


@app.delete("/api/logs/{session_id}", response_model=DeleteResult)
def delete_log(session_id: str):
    n = db.delete_session(session_id)
    if not n:
        raise HTTPException(status_code=404, detail="해당 세션의 실행 로그가 없어요.")
    return DeleteResult(deleted=n)


# ---------- 화면 (frontend/ 폴더가 생기면 같은 서버에서 제공) ----------
if os.path.isdir("frontend"):
    app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")