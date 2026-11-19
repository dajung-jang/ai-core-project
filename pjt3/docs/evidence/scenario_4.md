# 시나리오 4. Tool 하나가 실패하는 요청 (장소 검색 키를 일부러 비움)

- 실행 시각: 2026-11-19 20:40:44
- 세션 id: `evidence-s4` (화면의 '실행 로그' 탭에서도 볼 수 있음)
- 기대한 동작: 장소 검색 Tool만 MISSING_KEY로 실패하고, 추천과 나머지 단계는 정상 진행된다
- 시험 설정: KAKAO_REST_API_KEY를 임시로 비움(실행 후 복원)

## 요청 1

> 토요일 오전에 부산에서 초보가 탈 만한 곳과 근처 서핑샵도 알려줘

- 의도: `None` — None
- 추출된 조건: `{"date": null, "start_time": null, "end_time": null, "region": null, "level": null, "end_by": null, "wants_places": []}`
- 시도한 지역: [] / 재계획 0회
- 처리 시간: 3.3초 / LLM 호출 1회

### 최종 응답

```text
요청을 분석하지 못했습니다. 잠시 후 다시 시도해 주세요.
```

### Tool 호출 이력

(Tool 호출 없음)

## 자동 확인

| 확인 항목 | 결과 |
|---|---|
| search_places가 실패로 기록됐다 | **불일치** |
| 다른 Tool은 정상 호출됐다 | **불일치** |
| 추천 또는 제외 사유가 응답에 있다 | **불일치** |
| 서비스가 중단되지 않고 응답했다 | 일치 |

## 실행 로그 (이벤트, 실행 순서대로)

| seq | type | 내용 |
|---|---|---|
| 2 | error |  |
| 3 | step_end | analyze 3339ms |
| 5 | step_end | respond 0ms |

<details><summary>원본 이벤트 JSON</summary>

```json
[
 {
  "seq": 1,
  "ts": "2026-11-19T20:40:40.908+09:00",
  "type": "step_start",
  "payload": {
   "step": "analyze"
  }
 },
 {
  "seq": 2,
  "ts": "2026-11-19T20:40:44.246+09:00",
  "type": "error",
  "payload": {
   "step": "analyze",
   "error": "RateLimitError"
  }
 },
 {
  "seq": 3,
  "ts": "2026-11-19T20:40:44.249+09:00",
  "type": "step_end",
  "payload": {
   "step": "analyze",
   "elapsed_ms": 3339,
   "intent": null,
   "reason": "LLM 호출 실패"
  }
 },
 {
  "seq": 4,
  "ts": "2026-11-19T20:40:44.251+09:00",
  "type": "step_start",
  "payload": {
   "step": "respond"
  }
 },
 {
  "seq": 5,
  "ts": "2026-11-19T20:40:44.253+09:00",
  "type": "step_end",
  "payload": {
   "step": "respond",
   "elapsed_ms": 0,
   "length": 32
  }
 }
]
```

</details>

## 기대한 동작과 실제 동작의 차이

(직접 기록: 자동 확인이 모두 '일치'면 '차이 없음', 불일치가 있으면 원인과 수정 내용을 적는다)
