# 3. Tool 정의서

## 1. 공통 규칙 (F3001, `tools/base.py`)

### 응답 형식

```json
// 성공
{"ok": true, "data": { ... }}
// 실패
{"ok": false, "error": {"code": "RATE_LIMITED", "message": "사용자에게 보여줄 수 있는 안내문"}}
```

- 모든 Tool 함수에 `@safe_tool`을 적용해 **예외가 밖으로 새지 않고** `UNKNOWN`으로 변환됩니다.
- 오류 메시지에는 키 값·내부 경로를 담지 않습니다.

### 오류 코드

| 코드 | 의미 | Agent의 처리 |
|---|---|---|
| `MISSING_KEY` | API 키 미설정 | 재시도 안 함, 즉시 중단 + 설정 안내 |
| `INVALID_INPUT` | 인자 형식·범위 오류 | 재시도 안 함, 즉시 중단 |
| `AUTH_ERROR` | 키 오류·권한 없음 | 재시도 안 함, 즉시 중단 + 설정 안내 |
| `RATE_LIMITED` | 호출 한도 초과 | 재시도 안 함, 해당 스팟 판정 불가 |
| `HTTP_ERROR` | 연결 실패·서버 오류 | 같은 인자로 1회 재시도 |
| `PARSE_ERROR` | 응답 해석 실패 | 같은 인자로 1회 재시도 |
| `UNKNOWN` | 예상 못한 예외 | 같은 인자로 1회 재시도 |
| `NO_DATA` | 해당 조건의 데이터 없음 | 재시도 안 함, 해당 스팟 판정 불가 |

`NON_RETRYABLE = {MISSING_KEY, INVALID_INPUT, AUTH_ERROR}` / `RETRY_ONCE = {HTTP_ERROR, PARSE_ERROR, UNKNOWN}` (`agent/nodes.py`)

### 등록·확장 방법

1. `tools/` 아래에 새 파일을 만들고 함수에 `@register_tool(name, description, parameters)`와 `@safe_tool`을 붙입니다.
2. `description`에는 **언제 쓰고 언제 쓰지 않는지**를 적고, `parameters`는 JSON Schema(가능하면 `enum`)로 적습니다.
3. `tools/__init__.py`에서 새 모듈을 import하면 `TOOL_REGISTRY`에 등록되고 `tool_specs()`로 LLM용 스키마가 만들어집니다.
4. 현재 Tool 호출 순서는 `agent/nodes.py`의 `build_tasks`(규칙)가 정하므로, **새 Tool을 실제 흐름에 쓰려면 `build_tasks`(또는 `places` 같은 노드)에 작업을 추가**해야 합니다. 레지스트리에 등록만 해서는 자동으로 호출되지 않습니다.
5. `agent/nodes.py`의 `_summarize`에 요약 규칙을 추가해(원본 응답을 맥락·로그에 쌓지 않기 위함) 필요한 값만 남깁니다.
6. `scripts/check_tools.py`에 실제 호출 확인을, `scripts/`에 실패 케이스 테스트를 추가합니다.

---

## 2. get_wave_forecast — 파고 예보 (F3002, `tools/wave.py`)

| 항목 | 내용 |
|---|---|
| 설명 | 지역의 후보 스팟별 예상 최대 파고를 조회한다 |
| 외부 API | Open-Meteo Marine (`marine-api.open-meteo.com/v1/marine`, 키 불필요) |
| 지원 지역 | `spots.py`의 지역: 양양, 포항, 부산, 제주 |

**입력**

| 이름 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `region` | string | ✅ | 지역 이름 (지원 목록 중 하나) |
| `date` | string | ✅ | `YYYY-MM-DD` (누락 시 되묻도록 Agent가 막음) |
| `start_time` | string | | `HH:MM`, 기본 06:00 |
| `end_time` | string | | `HH:MM`, 기본 12:00 |

**출력(`data`)** — Agent가 쓰는 핵심 필드:

```json
{"region": "양양", "date": "2026-11-21", "window": {"start": "06:00", "end": "12:00"},
 "spots": [{"spot_id": "yy_jukdo", "name": "양양 죽도", "max_wave_height_m": 0.5, "...": "..."}]}
```

> 전체 필드는 `tools/wave.py`의 반환 부분을 기준으로 합니다. 위는 `_summarize`가 읽는 필드입니다. 같은 지역 스팟은 같은 격자의 값을 쓸 수 있습니다.

**실패 케이스**

| 상황 | 코드 | 메시지 성격 |
|---|---|---|
| 지원하지 않는 지역 / 날짜·시각 형식 오류 | `INVALID_INPUT` | 올바른 형식 안내 |
| 연결 실패·서버 오류 | `HTTP_ERROR` | 연결하지 못함 |
| 한도 초과(429) | `RATE_LIMITED` | 한도 초과 |
| 응답 해석 실패 | `PARSE_ERROR` | 해석 실패 |
| 해당 시간대 값 없음 | `NO_DATA` | 데이터 없음 |

> 자세한 분기 조건은 `tools/wave.py`와 `scripts/check_tools.py` 실행 결과로 확인하세요.

---

## 3. get_beach_weather — 해변 날씨 (F3003, `tools/beach.py`)

| 항목 | 내용 |
|---|---|
| 설명 | 후보 스팟의 해변별 바람(풍속·풍향)·기온·강수 예보와, **오늘 날짜일 때** 현재 실측 파고·수온을 조회한다. 파고 Tool로 후보를 얻은 뒤 사용한다 |
| 외부 API | 기상청 전국 해수욕장 날씨 `getVilageFcstBeach`(예보), `getWhBuoyBeach`(파고 실측), `getTwBuoyBeach`(수온 실측) — 키 `DATA_GO_KR_KEY_BEACH` |

**입력**

| 이름 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `spot_ids` | string[] | ✅ | `spots.py`의 스팟 id 목록 (enum) |
| `date` | string | ✅ | `YYYY-MM-DD` |
| `start_time` | string | | `HH:MM` (사용자가 말한 경우만), 기본 06:00 |
| `end_time` | string | | `HH:MM`, 기본 12:00 (`start ≤ end` 필요) |

**출력(`data`)**

```json
{"date": "2026-11-19", "window": {"start": "06:00", "end": "12:00"},
 "source": "기상청 전국 해수욕장 날씨 조회서비스", "note": "...",
 "spots": [{"spot_id": "...", "name": "...", "beach_num": 304,
            "forecast_base": "...", "hourly": [ {"time": "...", "wind_speed_ms": 3.2, "...": "..."} ],
            "max_wind_speed_ms": 4.1,
            "observed": {"wave_height_m": 0.4, "water_temp_c": 17.0}}]}
```

- 풍속 = √(UUU² + VVV²) (동서·남북 성분으로 계산). `±900` 이상은 결측으로 `None`.
- `observed`는 **오늘 날짜일 때만** 조회하고, 그 외에는 `None`입니다.
- 스팟 단위로 실패하면 해당 항목에 `error: {code, message}`가 들어가고 **나머지 스팟은 정상 반환**합니다. 모든 스팟이 실패했을 때만 Tool 전체가 실패합니다.

**실패 케이스**

| 상황 | 코드 |
|---|---|
| 키 미설정 | `MISSING_KEY` |
| `spot_ids` 비었음/미지원 id, 날짜·시각 형식 오류, `start > end` | `INVALID_INPUT` |
| 공공데이터포털 `resultCode` 인증·권한 오류 | `AUTH_ERROR` |
| 호출 한도 초과 | `RATE_LIMITED` |
| 연결 실패·서버 오류 | `HTTP_ERROR` |
| 응답 해석 실패 | `PARSE_ERROR` |
| 날짜·시간대 예보 없음(단기예보 제공 기간 밖) | `NO_DATA` |

(`resultCode` → 오류 코드 대응표는 `tools/beach.py`의 `CODE_MAP`)

---

## 4. search_places — 주변 장소 검색 (F3004, `tools/places.py`)

| 항목 | 내용 |
|---|---|
| 설명 | 서핑 스팟 주변의 서핑샵·숙소·맛집을 검색한다. **서핑 가능 여부 판단에는 쓰지 않는다** |
| 외부 API | Kakao Local 키워드 검색 — 키 `KAKAO_REST_API_KEY` |
| 검색 조건 | 스팟 좌표 중심 반경 5,000 m, 거리순 |

**입력**

| 이름 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `spot_id` | string | ✅ | 스팟 id (enum) |
| `category` | string | ✅ | `서핑샵` / `숙소` / `맛집` (내부 검색어: 서핑샵 / 숙박 / 맛집) |
| `size` | integer | | 기본 5, 최대 10 (범위를 벗어나면 보정) |

**출력(`data`)**

```json
{"spot_id": "yy_jukdo", "spot_name": "양양 죽도", "category": "맛집", "radius_m": 5000, "source": "카카오 로컬",
 "places": [{"name": "...", "address": "...", "phone": null, "distance_m": 320,
             "category_name": "...", "place_url": "..."}]}
```

**실패 케이스**

| 상황 | 코드 |
|---|---|
| 미지원 스팟·카테고리, `size`가 숫자 아님, HTTP 400(쿼터 아님) | `INVALID_INPUT` |
| 키 미설정 | `MISSING_KEY` |
| HTTP 401 / 403(카카오맵 사용 설정 안 함 등) | `AUTH_ERROR` |
| HTTP 429, 또는 HTTP 400 + 에러 코드 -10(쿼터 초과) | `RATE_LIMITED` |
| 연결 실패, 그 외 비정상 상태 코드 | `HTTP_ERROR` |
| JSON 아님·`documents` 없음 | `PARSE_ERROR` |
| 검색 결과 0건 | `NO_DATA` |

위 분기는 `scripts/test_places_quota.py`가 자동으로 확인합니다(400+코드 -10, 429, 400, JSON 없음, 401, 빈 결과).

---

## 5. Tool 호출 규칙 요약 (Agent 쪽)

- 호출 순서: `get_wave_forecast` → `get_beach_weather`(파고 결과의 후보 스팟만) → 필요 시 `search_places`(1순위 스팟).
- 같은 이름·인자의 **성공** 결과는 `tool_cache`에서 재사용합니다(재계획·후속 요청).
- 이벤트: 호출마다 `tool_request` / `tool_response`(요약, 소요 ms, 캐시 여부, 시도 횟수)가 기록됩니다.