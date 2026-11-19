"""대표 시나리오 5종을 실제 LLM·실제 API로 실행하고 증빙을 docs/evidence/ 에 저장한다 (4.7).

실행(프로젝트 루트):  python -m scripts.run_scenarios          # 전체
                      python -m scripts.run_scenarios 2 3      # 골라서
세션은 evidence-s1 ... 이름으로 실행 로그 DB에 남으므로, 화면의 '실행 로그' 탭에서도 볼 수 있다.
"""
import json
import os
import sys
import time

import config
from agent import llm
from agent.graph import reset_session, run_turn
from logging_agent import collector
from store import db

OUT_DIR = os.path.join("docs", "evidence")

SCENARIOS = {
    1: {"title": "제약을 한 번에 충족하는 요청",
        "turns": ["토요일 오전에 부산에서 초보가 탈 만한 곳 찾아줘"],
        "expect": "부산 안에서 후보가 나와 재계획 없이 끝난다 (날씨가 기준을 넘는 날이면 달라질 수 있음)"},
    2: {"title": "재계획이 필요한 요청 + 후속 요청(조건 일부만 변경)",
        "turns": ["토요일 오전에 양양에서 초보가 탈 만한 곳 찾아줘, 오후 2시 전엔 나와야 해",
                  "포항은?"],
        "expect": "양양이 기준을 넘으면 인접 지역으로 재계획한다. 후속 요청은 지역만 바뀌고 날짜·시각은 유지되며, 이미 받은 Tool 결과는 다시 호출하지 않는다"},
    3: {"title": "재계획 상한에 도달하는 요청 (판단 기준을 비현실적으로 좁혀 강제)",
        "turns": ["토요일 오전에 양양에서 초보가 탈 만한 곳 찾아줘"],
        "expect": "재계획이 상한(MAX_REPLAN)까지 일어나고, 사유와 함께 멈추며 조건 조정을 되묻는다",
        "setup": "LEVEL_LIMITS['초보']를 파고 0.05m·풍속 0.1m/s로 임시 변경(실행 후 복원). 실제 날씨로는 모든 지역이 부적합인 날을 기다릴 수 없어서 강제함"},
    4: {"title": "Tool 하나가 실패하는 요청 (장소 검색 키를 일부러 비움)",
        "turns": ["토요일 오전에 부산에서 초보가 탈 만한 곳과 근처 서핑샵도 알려줘"],
        "expect": "장소 검색 Tool만 MISSING_KEY로 실패하고, 추천과 나머지 단계는 정상 진행된다",
        "setup": "KAKAO_REST_API_KEY를 임시로 비움(실행 후 복원)"},
    5: {"title": "Tool이 필요 없는 요청",
        "turns": ["안녕! 이 서비스는 뭘 할 수 있어?"],
        "expect": "Tool을 한 번도 호출하지 않고 안내/되묻기로 끝난다"},
}


def _checks(n, turns):
    """시나리오별 자동 확인 항목. (설명, True/False)"""
    last, first = turns[-1], turns[0]
    calls = [t for tr in turns for t in tr["final"].get("tool_log", [])]
    if n == 1:
        return [("Tool을 호출했다", bool(first["final"]["tool_log"])),
                ("재계획 0회", first["final"]["replan_count"] == 0),
                ("오류 없이 응답했다", not first["final"].get("fatal_error"))]
    if n == 2:
        t2 = turns[1]["final"]
        return [("첫 요청에서 재계획이 1회 이상 일어났다", first["final"]["replan_count"] >= 1),
                ("후속 요청에서 바뀐 조건은 지역뿐이다", t2["changed_conditions"] == ["region"]),
                ("후속 요청에서 날짜가 유지됐다", t2["conditions"]["date"] == first["final"]["conditions"]["date"]),
                ("후속 요청의 Tool 호출이 모두 캐시 재사용이다", bool(t2["tool_log"]) and all(c["cached"] for c in t2["tool_log"]))]
    if n == 3:
        f = first["final"]
        return [(f"재계획 {config.MAX_REPLAN}회에서 멈췄다", f["replan_count"] == config.MAX_REPLAN),
                ("후보가 없다", not f["candidates"]),
                ("조건 조정을 되묻는다", "조정" in f["answer"])]
    if n == 4:
        f = first["final"]
        failed = [c for c in f["tool_log"] if c["tool"] == "search_places" and not c["ok"]]
        return [("search_places가 실패로 기록됐다", bool(failed) and failed[0]["error_code"] == "MISSING_KEY"),
                ("다른 Tool은 정상 호출됐다", any(c["ok"] for c in f["tool_log"] if c["tool"] != "search_places")),
                ("추천 또는 제외 사유가 응답에 있다", "추천" in f["answer"] or "제외한 곳" in f["answer"]),
                ("서비스가 중단되지 않고 응답했다", bool(f["answer"]))]
    if n == 5:
        return [("Tool 호출이 0회다", not first["final"]["tool_log"]), ("응답이 있다", bool(first["final"]["answer"]))]
    return []


def _brief(e):
    p = e["payload"]
    if e["type"] in ("step_start", "step_end"):
        extra = f" {p['elapsed_ms']}ms" if "elapsed_ms" in p else ""
        return f"{p.get('step')}{extra}"
    if e["type"] in ("tool_request", "tool_response"):
        return f"{p.get('tool')}" + (" (캐시)" if p.get("cached") else "") + \
               (f" ok={p['ok']}" if "ok" in p else "") + (f" {p['elapsed_ms']}ms" if "elapsed_ms" in p else "")
    if e["type"] == "replan":
        return f"{p.get('count')}회 → {p.get('next_region')}"
    if e["type"] == "judge_result":
        return f"{p.get('region')}: " + ", ".join(f"{s.get('name', s['spot_id'])} {s['grade']}" for s in p.get("spots", []))
    return ""


def run_one(n, out_dir):
    sc = SCENARIOS[n]
    sid = f"evidence-s{n}"
    db.delete_session(sid)
    reset_session(sid)
    saved = {}
    if n == 3:
        saved["limits"] = dict(config.LEVEL_LIMITS["초보"])
        config.LEVEL_LIMITS["초보"].update(wave_min_m=0.0, wave_caution_m=0.03, wave_max_m=0.05, wind_max_ms=0.1)
    if n == 4:
        saved["kakao"] = config.KAKAO_REST_API_KEY
        config.KAKAO_REST_API_KEY = None
    turns = []
    try:
        for text in sc["turns"]:
            t0 = time.perf_counter()
            llm_before = _LLM_CALLS["n"]
            final = run_turn(sid, text)
            turns.append({"text": text, "final": final, "sec": round(time.perf_counter() - t0, 1),
                          "llm": _LLM_CALLS["n"] - llm_before})
    finally:
        if "limits" in saved:
            config.LEVEL_LIMITS["초보"].update(saved["limits"])
        if "kakao" in saved:
            config.KAKAO_REST_API_KEY = saved["kakao"]

    events = db.get_session_events(sid)
    checks = _checks(n, turns)
    lines = [f"# 시나리오 {n}. {sc['title']}", "",
             f"- 실행 시각: {time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"- 세션 id: `{sid}` (화면의 '실행 로그' 탭에서도 볼 수 있음)",
             f"- 기대한 동작: {sc['expect']}"]
    if sc.get("setup"):
        lines.append(f"- 시험 설정: {sc['setup']}")
    for i, t in enumerate(turns, 1):
        f = t["final"]
        lines += ["", f"## 요청 {i}", "", f"> {t['text']}", "",
                  f"- 의도: `{f.get('intent')}` — {f.get('intent_reason')}",
                  f"- 추출된 조건: `{json.dumps(f['conditions'], ensure_ascii=False)}`",
                  f"- 시도한 지역: {f.get('tried_regions')} / 재계획 {f.get('replan_count')}회",
                  f"- 처리 시간: {t['sec']}초 / LLM 호출 {t['llm']}회", "",
                  "### 최종 응답", "", "```text", f["answer"], "```", "",
                  "### Tool 호출 이력", ""]
        if f["tool_log"]:
            lines += ["| # | Tool | 인자 | 결과 | 소요 | 재계획 회차 |", "|---|---|---|---|---|---|"]
            for k, c in enumerate(f["tool_log"], 1):
                res = "캐시 재사용" if c["cached"] else ("성공" if c["ok"] else f"실패 {c['error_code']}")
                lines.append(f"| {k} | {c['tool']} | `{json.dumps(c['args'], ensure_ascii=False)}` | {res} | "
                             f"{'-' if c['cached'] else str(c['elapsed_ms']) + 'ms'} | {c['replan_count']} |")
        else:
            lines.append("(Tool 호출 없음)")
    lines += ["", "## 자동 확인", "", "| 확인 항목 | 결과 |", "|---|---|"]
    lines += [f"| {d} | {'일치' if ok else '**불일치**'} |" for d, ok in checks]
    lines += ["", "## 실행 로그 (이벤트, 실행 순서대로)", "", "| seq | type | 내용 |", "|---|---|---|"]
    lines += [f"| {e['seq']} | {e['type']} | {_brief(e)} |" for e in events if e["type"] != "step_start"]
    lines += ["", "<details><summary>원본 이벤트 JSON</summary>", "", "```json",
              json.dumps(events, ensure_ascii=False, indent=1), "```", "", "</details>", "",
              "## 기대한 동작과 실제 동작의 차이", "", "(직접 기록: 자동 확인이 모두 '일치'면 '차이 없음', 불일치가 있으면 원인과 수정 내용을 적는다)", ""]
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"scenario_{n}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return {"n": n, "title": sc["title"], "turns": turns, "checks": checks, "path": path}


_LLM_CALLS = {"n": 0}


def main(argv=None, out_dir=OUT_DIR):
    wanted = [int(a) for a in (argv if argv is not None else sys.argv[1:])] or sorted(SCENARIOS)
    orig = llm.chat

    def counting(*a, **k):
        _LLM_CALLS["n"] += 1
        return orig(*a, **k)
    llm.chat = counting
    collector.start()
    results = []
    for n in wanted:
        print(f"[시나리오 {n}] {SCENARIOS[n]['title']} ...", flush=True)
        r = run_one(n, out_dir)
        bad = [d for d, ok in r["checks"] if not ok]
        print(f"   -> {r['path']}  자동 확인 {len(r['checks']) - len(bad)}/{len(r['checks'])} 일치"
              + (f"  불일치: {bad}" if bad else ""))
        results.append(r)
    rows = ["# 대표 시나리오 실행 요약", "", f"- 실행 시각: {time.strftime('%Y-%m-%d %H:%M:%S')}", "",
            "| # | 시나리오 | 요청 수 | 재계획 | Tool 호출 | 처리 시간(합) | 자동 확인 |", "|---|---|---|---|---|---|---|"]
    for r in results:
        calls = sum(len(t["final"]["tool_log"]) for t in r["turns"])
        replans = ", ".join(str(t["final"]["replan_count"]) for t in r["turns"])
        sec = round(sum(t["sec"] for t in r["turns"]), 1)
        ok = sum(1 for _, v in r["checks"] if v)
        rows.append(f"| {r['n']} | [{r['title']}](scenario_{r['n']}.md) | {len(r['turns'])} | {replans} | {calls} | {sec}초 | {ok}/{len(r['checks'])} |")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + "\n")
    print(f"\n요약: {os.path.join(out_dir, 'summary.md')}")
    return results


if __name__ == "__main__":
    main()