# 4. API 명세서
 
- 서버: FastAPI (`uvicorn backend.main:app --reload`), 기본 주소 `http://127.0.0.1:8000`
- 자동 문서: `/docs` (Swagger UI), `/openapi.json`
- 형식: JSON (UTF-8). 화면(`frontend/`)은 같은 서버의 `/` 에서 제공됩니다.
- 오류 응답: FastAPI 기본 형식 `{"detail": "메시지"}`
| 구분 | Method | 경로 | 설명 |
|---|---|---|---|
| 상태 | GET | `/api/health` | 서버 상태와 키 설정 여부 |
| 대화 | POST | `/api/chat` | Agent에게 요청 |
| 계획 | GET | `/api/plans` | 저장된 계획 목록 |
| 계획 | GET | `/api/plans/{plan_id}` | 계획 1건 |
| 계획 | PATCH | `/api/plans/{plan_id}` | 계획 수정 |
| 계획 | DELETE | `/api/plans/{plan_id}` | 계획 삭제 |
| 로그 | GET | `/api/logs` | 실행 로그 세션 목록 |
| 로그 | GET | `/api/logs/{session_id}` | 세션의 이벤트 목록 |
| 로그 | DELETE | `/api/logs/{session_id}` | 세션 로그 삭제 |
 
> 계획은 **대화로만 생성**됩니다(“2번 저장해 줘”). 계획 생성용 `POST` API는 없습니다. 로그는 **수정 API가 없습니다**(조회·삭제만).
 
---
 
## 1. GET /api/health
 
**응답 200** — `HealthOut`
 
```json
{"status": "ok",
 "keys": {"llm": true, "beach": true, "kakao": false},
 "missing_guide": ["장소 검색 키(KAKAO_REST_API_KEY)가 없어요. 카카오 REST API 키를 .env에 넣어 주세요."]}
```
 
`keys`는 키 존재 여부만 알려주며 **키 값은 절대 내려주지 않습니다.**
 
## 2. POST /api/chat
 
**요청** — `ChatRequest`
 
| 필드 | 타입 | 필수 | 제약 |
|---|---|---|---|
| `session_id` | string | | `^[A-Za-z0-9_-]{1,64}$`. 없으면 서버가 새로 만들어 응답에 담아줌 |
| `message` | string | ✅ | 1~500자 |
 
```json
{"session_id": "demo1", "message": "이번 주 토요일 오전, 초보인데 양양에서 서핑할 수 있어?"}
```
 
**응답 200** — `ChatResponse`
 
| 필드 | 타입 | 설명 |
|---|---|---|
| `session_id` | string | 이어서 대화할 때 다시 보낼 값 |
| `answer` | string | 최종 답변(출처·면책 포함) |
| `intent` | string \| null | `plan_request` `modify_request` `save_plan` `need_info` `out_of_scope` |
| `intent_reason` | string \| null | 분류 이유 한 문장 |
| `conditions` | object | 현재 조건 `{date, start_time, end_time, region, level, end_by, wants_places}` |
| `replan_count` | integer | 이번 요청의 재계획 횟수 |
| `tried_regions` | string[] | 확인한 지역 순서 |
| `tool_log` | object[] | `{tool, args, ok, cached, elapsed_ms, error_code, replan_count}` |
| `events` | object[] | 이번 요청에서 발생한 이벤트 `{seq, ts, type, payload}` (순서대로) |
| `error` | `{code, message}` \| null | 치명 오류(키 누락 등). 화면에 설정 안내를 띄움 |
 
```json
{"session_id": "demo1",
 "answer": "2026-11-21 06:00~12:00 · 초보 기준으로 확인한 결과예요.\n\n추천\n1. 양양 죽도 — 적합 (최대 파고 0.45m, 최대 풍속 3.1m/s)\n ...",
 "intent": "plan_request", "intent_reason": "서핑 가능 여부를 새로 묻는 요청",
 "conditions": {"date": "2026-11-21", "region": "양양", "level": "초보", "...": null},
 "replan_count": 0, "tried_regions": ["양양"],
 "tool_log": [{"tool": "get_wave_forecast", "args": {"region": "양양", "date": "2026-11-21"},
               "ok": true, "cached": false, "elapsed_ms": 820, "error_code": null, "replan_count": 0}],
 "events": [{"seq": 1, "ts": "2026-11-19T19:00:00+09:00", "type": "step_start", "payload": {"step": "analyze"}}],
 "error": null}
```
 
(수치는 형식을 보여 주기 위한 예시입니다. 실제 실행 결과는 [검증 결과](05_검증결과.md)의 기록을 보세요.)
 
**오류**
 
| 상태 | 상황 |
|---|---|
| 422 | 요청 형식 오류(빈 메시지, 500자 초과, 잘못된 `session_id`) |
| 500 | Agent 처리 중 예기치 못한 오류 — `{"detail": "요청을 처리하는 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요."}` |
 
> Tool·LLM 실패는 500이 아니라 **200 + `error` 필드**(또는 답변 문장)로 알려줍니다. 같은 `session_id`의 요청은 서버에서 순서대로 처리합니다.
 
## 3. 계획 관리
 
### PlanOut
 
```json
{"id": 1, "spot_id": "yy_jukdo", "spot_name": "양양 죽도", "date": "2026-11-21",
 "start_time": "07:00", "end_time": "09:00", "note": null,
 "created_at": "2026-11-19T19:05:00+09:00", "updated_at": null}
```
 
### GET /api/plans → `PlanOut[]`
 
### GET /api/plans/{plan_id} → `PlanOut` (없으면 404 `계획을 찾을 수 없어요.`)
 
### PATCH /api/plans/{plan_id}
 
**요청** — `PlanUpdate` (보낸 항목만 수정, 하나 이상 필요)
 
| 필드 | 형식 |
|---|---|
| `date` | `YYYY-MM-DD` |
| `start_time`, `end_time` | `HH:MM` |
| `note` | 최대 300자 |
 
**응답 200** — `PlanUpdateResult`
 
```json
{"plan": { "...PlanOut..." },
 "overlaps": [ { "...같은 날 시간이 겹치는 다른 계획..." } ]}
```
 
- 시간이 겹쳐도 **수정은 반영**되고 `overlaps`로 알려줍니다(화면에서 경고).
- 422: 보낸 값이 없거나, 시작이 종료보다 늦는 등 값이 올바르지 않을 때 / 404: 계획 없음
### DELETE /api/plans/{plan_id} → `{"deleted": 1}` (없으면 404)
 
## 4. 실행 로그
 
### SessionSummary
 
```json
{"session_id": "demo1", "event_count": 24, "started_at": "...", "last_at": "...",
 "error_count": 0, "replan_count": 1}
```
 
### GET /api/logs → `SessionSummary[]`
 
### GET /api/logs/{session_id} → `{"session_id": "...", "events": [{seq, ts, type, payload}, ...]}` (없으면 404)
 
### DELETE /api/logs/{session_id} → `{"deleted": <삭제한 이벤트 수>}` (없으면 404)
 
### 이벤트 type과 payload
 
| type | payload 주요 필드 |
|---|---|
| `step_start` | `step` |
| `step_end` | `step`, 단계별 결과 요약(analyze: intent·reason·conditions / plan: region·tasks / judge: candidates·excluded 수 …) |
| `tool_request` | `tool`, `args`, `attempt` |
| `tool_response` | `tool`, `ok`, `elapsed_ms`, `attempt`, `summary`(성공) 또는 `error`(실패), `cached` |
| `judge_result` | `region`, `level`, `spots[{spot_id,name,grade,reasons,warnings,wave_max_m,wind_max_ms}]`, `candidates` |
| `replan` | `count`, `reason`, `next_region`, `tried` |
| `plan_saved` | 저장된 계획 정보 |
| `error` | `code`, `message` |
 
> `llm_decision` 타입은 정의만 있고 현재 발생하지 않습니다.
 
## 5. 호출 예 (curl)
 
```bash
curl -s http://127.0.0.1:8000/api/health
curl -s -X POST http://127.0.0.1:8000/api/chat -H "Content-Type: application/json" \
  -d '{"session_id":"demo1","message":"내일 양양에서 서핑할 수 있어?"}'
curl -s http://127.0.0.1:8000/api/plans
curl -s -X PATCH http://127.0.0.1:8000/api/plans/1 -H "Content-Type: application/json" \
  -d '{"start_time":"08:00","end_time":"10:00"}'
curl -s http://127.0.0.1:8000/api/logs
```
 