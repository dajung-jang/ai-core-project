# 🏄 서핑 플래너 — Agent 기반 도메인 플래너 서비스

SSAFY AI Core Project 3회차. 2회차의 서핑 도메인을 이어서, **"날짜·시간·실력 같은 제약을 말하면 Agent가 파도·바람·주변 정보를 직접 조회하고, 조건에 맞는 스팟을 골라 계획으로 저장해 주는"** 서비스입니다.

> 예) "이번 주 토요일 오전, 초보인데 양양에서 서핑할 수 있어? 점심 전에는 나와야 해"
> → 파고·풍속 조회 → 판정 → (조건에 맞는 곳이 없으면 가까운 지역으로 재계획) → 추천 + 근거 → "2번 저장해 줘" → 계획 저장

---

## 1. 구성 한눈에 보기

| 영역 | 내용 |
|---|---|
| Agent | LangGraph `StateGraph` — `analyze → plan → work → judge → (replan → work …) → respond`, 저장 요청은 `analyze → save` |
| LLM 사용 | **요청 분석(analyze) 한 곳만**. 판정·재계획·답변 작성은 규칙/코드로 처리(숫자가 바뀌지 않도록) |
| Tool | `get_wave_forecast`(파고), `get_beach_weather`(바람·날씨·실측), `search_places`(서핑샵·숙소·맛집) |
| 로깅 Agent | 메인 Agent는 이벤트만 `emit`, 로깅 Agent가 구독해 SQLite에 저장(메인은 로깅이 있는지 모름) |
| 백엔드 | FastAPI + Pydantic, SQLite |
| 프론트 | 순수 HTML/CSS/JS (대화 · 내 계획 · 실행 로그 탭) |
| 선택 도메인 | 서핑 (2회차에서 이어짐) |

### 필수 / 심화 구분

| 구분 | 요구사항 | 상태 |
|---|---|---|
| 필수 | F3001 ~ F3019 | ✅ 구현 |
| 심화 | F3020 ~ F3023 | ⏸ **이번 제출에서는 선택하지 않음** |

기능별 구현 위치와 상태는 [`docs/01_요구사항정의서.md`](docs/01_요구사항정의서.md)에 있습니다.

---

## 2. 실행 방법

### 2-1. 준비 (Git Bash 기준)

```bash
python -m venv venv
source venv/Scripts/activate        # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                # 만든 뒤 .env를 열어 키를 채웁니다
```

### 2-2. 서버 실행

```bash
uvicorn backend.main:app --reload   # 프로젝트 루트에서 실행
```

- 화면: http://127.0.0.1:8000
- API 문서(자동 생성): http://127.0.0.1:8000/docs
- 필요한 키가 비어 있으면 화면 상단에 어떤 키를 넣어야 하는지 안내가 뜹니다(`GET /api/health`).

### 2-3. 터미널로만 써 보기 / 점검 스크립트

```bash
python -m scripts.chat_cli                # 화면 없이 대화 (이벤트·Tool 호출 출력)
python -m scripts.check_tools             # 실제 외부 API 호출 확인
python -m scripts.run_scenarios           # 대표 시나리오 5개를 실제로 실행해 docs/evidence/ 에 기록
python -m scripts.print_graph             # Agent 그래프를 Mermaid로 출력
```

### 2-4. 자동 테스트 (LLM·외부 API 없이 실행됨)

```bash
python -m scripts.test_judge
python -m scripts.test_state
python -m scripts.test_store
python -m scripts.test_nodes
python -m scripts.test_graph
python -m scripts.test_save
python -m scripts.test_places_quota
python -m scripts.test_api
```

---

## 3. API 키 발급·설정 절차 (요약)

`.env`에 아래 값을 넣습니다. **`.env`는 `.gitignore`에 들어 있어 커밋되지 않습니다.**

| 변수 | 용도 | 발급처 |
|---|---|---|
| `GMS_KEY`, `GMS_BASE_URL`, `LLM_MODEL` | 요청 분석용 LLM (OpenAI 호환 API) | SSAFY GMS |
| `DATA_GO_KR_KEY_BEACH` | 기상청 전국 해수욕장 날씨 | [공공데이터포털](https://www.data.go.kr/data/15102239/openapi.do) → 활용신청 → 마이페이지 일반 인증키 |
| `KAKAO_REST_API_KEY` | 장소 검색 | [Kakao Developers](https://developers.kakao.com) → 앱 생성 → **카카오맵(로컬) 사용 설정 ON** → REST API 키 |
| `DATA_GO_KR_KEY_VILAGE` | (현재 앱에서 사용하지 않음) 점검용으로만 남겨 둔 키 | — |
| (키 불필요) | Open-Meteo Marine | 키 없이 사용 |

자세한 키 누락 시 동작은 [Tool 정의서](docs/03_Tool정의서.md)의 실패 케이스 표를 참고하세요.

---

## 4. 외부 API 출처와 이용 조건

2026-11-19 기준으로 각 제공처 문서에서 확인한 내용입니다. 정책은 바뀔 수 있습니다.

| API | 쓰는 곳 | 호출 한도(무료) | 이용 조건 |
|---|---|---|---|
| [Open-Meteo Marine](https://open-meteo.com/en/docs/marine-weather-api) | 파고 예보 | 분당 600 / 시간당 5,000 / 일 10,000 / 월 300,000 (월 한도는 아직 적용되지 않는다고 안내됨) | **비상업적 이용 한정**, CC BY 4.0 → 출처 표기 필요(답변 하단에 출처 문구 포함) |
| [기상청 전국 해수욕장 날씨](https://www.data.go.kr/data/15102239/openapi.do) (공공데이터포털) | 해변별 바람·기온·강수 예보, 파고·수온 실측 | 개발계정 일 10,000건 | 이용허락범위 제한 없음 |
| [Kakao Local 키워드 검색](https://developers.kakao.com/docs/latest/ko/local/dev-guide) | 서핑샵·숙소·맛집 | 일 100,000건 (개발자 계정당 **처음 활성화한 앱 1개**만 무료 — 2026-07-21 정책 변경) | 카카오 이용약관·정책 준수. 쿼터 초과 시 HTTP 400/에러 코드 -10 또는 429 |

> Open-Meteo는 비상업 조건이므로 이 프로젝트는 **교육용 과제**로만 사용합니다.

---

## 5. 폴더 구조

```
pjt3/
├─ agent/            # LangGraph 노드·그래프·판정·상태 (analyze/plan/work/judge/replan/respond/save)
├─ tools/            # Tool 3종 + 레지스트리(base.py)
├─ events/           # 이벤트 버스 (메인 Agent ↔ 로깅 Agent 연결점)
├─ logging_agent/    # 로깅 Agent (이벤트 구독 → SQLite)
├─ store/            # SQLite 접근 (계획, 이벤트 로그)
├─ backend/          # FastAPI (main.py, schemas.py)
├─ frontend/         # index.html, style.css, app.js
├─ scripts/          # CLI, 점검, 시나리오 실행, 테스트
├─ docs/             # 제출 문서 + evidence/(시나리오 실행 기록)
├─ spots.py          # 지원 스팟 9곳 (양양·포항·부산·제주)
├─ config.py         # 설정값(기준 수치·상한 등)
└─ .env.example
```

---

## 6. 제출 문서

| 번호 | 문서 |
|---|---|
| 1 | [요구사항 정의서](docs/01_요구사항정의서.md) |
| 2 | [Agent 설계 문서](docs/02_Agent설계문서.md) |
| 3 | [Tool 정의서](docs/03_Tool정의서.md) |
| 4 | [API 명세서](docs/04_API명세서.md) |
| 5 | [검증 결과](docs/05_검증결과.md) |
| 6 | [셀프 체크리스트](docs/06_셀프체크리스트.md) |
---

## 7. 알려진 한계 (솔직하게)

- **스팟은 9곳 고정 목록**입니다(양양 3 · 포항 2 · 부산 2 · 제주 2). 목록 밖 지역은 지원하지 않습니다.
- **판단 기준은 `초보`만** 있습니다. 중급/상급을 말하면 "초보 기준으로만 판단했다"고 답변에 밝힙니다.
- **서핑 시간은 2시간으로 가정**합니다(`SESSION_HOURS`). "몇 시까지 나와야 해"를 늦어도 시작해야 하는 시각으로 바꿀 때만 씁니다.
- **해변 방향(바람이 온쇼어/오프쇼어인지)은 반영하지 않습니다.** 풍속 크기만 봅니다.
- 파고는 **예보값**이라 실제와 다를 수 있습니다. 오늘 날짜는 실측과 비교해 차이가 0.5m 이상이면 경고합니다. 최종 판단은 현장 확인이 필요합니다.
- Tool은 지역별로 **순차 호출**합니다(3개 지역 확인에 약 10~11초 측정).
- Tool 선택은 현재 **규칙 기반**(항상 파고 → 해변 날씨)이며, 요청에 따라 LLM이 Tool을 고르는 구조는 아닙니다.
- `llm_decision` 이벤트 종류는 정의만 있고 **현재 발생시키지 않습니다**(LLM 호출이 analyze 한 곳뿐이라 `analyze`의 `step_end`가 그 기록을 겸합니다).
- 안전 면책: 이 서비스의 판정은 참고용이며 실제 입수 전 현장 상황·안전 수칙을 직접 확인해야 합니다.
- 종료 제한("몇 시까지 나와야 해")이 있으면 Tool은 그 시각까지 조회하지만, 답변 첫 줄의 시간대 문구는 사용자가 말한 시간대를 그대로 보여 줍니다.