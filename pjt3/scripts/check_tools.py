"""대표 요청 1을 Tool 순서대로 따라가는 설계 시험 (2.7 설계 시험, 4.1 Tool 확인)

요청: "토요일 오전에 양양에서 초보가 탈 만한 곳 찾아줘, 오후 2시 전엔 나와야 해"
실행: python scripts/check_tools.py   (프로젝트 루트에서)
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools.beach  # noqa: F401  (import하면 Tool이 레지스트리에 등록된다)
import tools.places  # noqa: F401
import tools.wave  # noqa: F401
from tools.base import TOOL_REGISTRY


def call(name, **kwargs):
    return TOOL_REGISTRY[name]["func"](**kwargs)


def show_error(step, res):
    print(f"[FAIL] {step}: {res['error']['code']} - {res['error']['message']}")


def main():
    today = date.today()
    saturday = today + timedelta((5 - today.weekday()) % 7 or 7)
    d = saturday.isoformat()
    print(f"요청 분석 결과(고정): 지역=양양, 날짜={d}, 시각=기본값, 제약=14:00 전 종료(Tool 인자 아님)\n")
    print("등록된 Tool:", list(TOOL_REGISTRY), "\n")

    # 1단계: 후보 스팟과 파고 예보
    wave = call("get_wave_forecast", region="양양", date=d)
    if not wave["ok"]:
        show_error("get_wave_forecast", wave)
        return
    spots = wave["data"]["spots"]
    spot_ids = [s["spot_id"] for s in spots]
    print(f"[OK] get_wave_forecast -> 후보 {len(spot_ids)}곳 {spot_ids}")

    # 2단계: 앞 Tool의 spot_id를 입력으로 바람·날씨
    beach = call("get_beach_weather", spot_ids=spot_ids, date=d)
    if not beach["ok"]:
        show_error("get_beach_weather", beach)
        return
    print(f"[OK] get_beach_weather <- get_wave_forecast의 spot_id {len(spot_ids)}개를 입력으로 사용")

    # 3단계: 보조 정보
    places = call("search_places", spot_id=spot_ids[0], category="서핑샵", size=3)
    if places["ok"]:
        names = [p["name"] for p in places["data"]["places"]]
        print(f"[OK] search_places <- {spot_ids[0]} -> {names}")
    else:
        show_error("search_places", places)

    # 4단계: 제약 판단에 쓸 값 모아보기 (판단 자체는 Agent 단계에서 구현)
    wind = {s["spot_id"]: s for s in beach["data"]["spots"]}
    print("\n스팟별 판단 재료 (Tool 결과 확인용 출력. 판단은 agent/judge.py에서 수행)")
    print(f"{'스팟':<12}{'최대 파고(m)':<14}{'최대 풍속(m/s)':<16}비고")
    for s in spots:
        w = wind.get(s["spot_id"], {})
        if "error" in w:
            print(f"{s['name']:<12}{str(s['max_wave_height_m']):<14}{'-':<16}{w['error']['code']}")
        else:
            print(f"{s['name']:<12}{str(s['max_wave_height_m']):<14}{str(w.get('max_wind_speed_ms')):<16}")


if __name__ == "__main__":
    main()