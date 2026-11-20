"""셀프 체크리스트 1번(F3001) 확인용: python -m scripts.checklist_tools
① Agent에 넘기는 Tool 목록 출력  ② Tool별 실패 호출(잘못된 입력, API 키 비움)  ③ 정상 호출 1회(실제 API)"""
import json

import config
import agent.nodes  # noqa: F401  (Tool 등록)
from tools.base import TOOL_REGISTRY, tool_specs

print("=== ① Agent에 넘기는 Tool 목록 ===")
for s in tool_specs():
    f = s["function"]
    print(f"- {f['name']}\n  설명: {f['description']}\n  입력: {json.dumps(f['parameters'], ensure_ascii=False)}")

BAD = {  # 잘못된 입력
    "get_wave_forecast": {"region": "없는지역", "date": "2026-11-21"},
    "get_beach_weather": {"spot_ids": ["없는스팟"], "date": "2026-11-21"},
    "search_places": {"spot_id": "없는스팟", "category": "서핑샵"},
}
GOOD = {  # 정상 호출
    "get_wave_forecast": {"region": "양양", "date": "2026-11-21"},
    "get_beach_weather": {"spot_ids": ["yy_jukdo"], "date": "2026-11-21"},
    "search_places": {"spot_id": "yy_jukdo", "category": "맛집", "size": 2},
}
KEY = {"get_beach_weather": "DATA_GO_KR_KEY_BEACH", "search_places": "KAKAO_REST_API_KEY"}  # 키가 필요한 Tool


def brief(r):
    if r["ok"]:
        return "ok=True (data 키: " + ", ".join(r["data"].keys()) + ")"
    return f"ok=False error={r['error']}"


print("\n=== ② 실패 호출 ===")
for name, tool in TOOL_REGISTRY.items():
    print(f"[{name}] 잘못된 입력 -> {brief(tool['func'](**BAD[name]))}")
    if name in KEY:
        old = getattr(config, KEY[name])
        setattr(config, KEY[name], "")
        try:
            print(f"[{name}] 키 비움({KEY[name]}) -> {brief(tool['func'](**GOOD[name]))}")
        finally:
            setattr(config, KEY[name], old)
    else:
        print(f"[{name}] 키 비움 -> 해당 없음 (이 Tool은 API 키가 필요 없음)")

print("\n=== ③ 정상 호출 ===")
for name, tool in TOOL_REGISTRY.items():
    print(f"[{name}] -> {brief(tool['func'](**GOOD[name]))}")

print("\n=== ④ F3002 기준 날짜 ===")
w = TOOL_REGISTRY["get_wave_forecast"]["func"]
r = w(region="양양")
print("날짜 없이 호출 ->", brief(r), "| date:", r.get("data", {}).get("date"),
      "| 기본값 적용:", r.get("data", {}).get("date_defaulted"))
print("   안내:", r.get("data", {}).get("note"))
print("먼 미래 날짜 ->", brief(w(region="양양", date="2027-12-31")))