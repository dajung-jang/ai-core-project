"""get_wave_forecast: Open-Meteo Marine으로 시간별 파고·파주기 예보 조회 (F3002)"""
import re
from datetime import datetime

import requests

import config
from spots import SPOTS
from tools.base import ErrorCode, fail, ok, register_tool, safe_tool

URL = "https://marine-api.open-meteo.com/v1/marine"
DEFAULT_START = "06:00"  # 시각을 말하지 않았을 때의 기본 조회 시간대
DEFAULT_END = "12:00"
REGIONS = sorted({s["region"] for s in SPOTS})
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@register_tool(
    name="get_wave_forecast",
    description=(
        "서핑 후보 지역의 시간별 파고·파주기 예보를 조회한다. "
        "사용자가 날짜와 지역을 말하고 서핑하기 좋은지, 어디서 탈 수 있는지 물을 때 사용한다. "
        "날짜나 지역을 모르면 호출하지 말고 사용자에게 되묻는다. "
        "시작·종료 시각은 사용자가 말한 경우에만 넣고, 말하지 않았으면 생략한다."
    ),
    parameters={
        "type": "object",
        "properties": {
            "region": {"type": "string", "enum": REGIONS, "description": "조회할 지역"},
            "date": {"type": "string", "description": "조회 날짜 YYYY-MM-DD (없으면 오늘 날짜로 조회)"},
            "start_time": {"type": "string", "description": "시작 시각 HH:MM (사용자가 말한 경우만)"},
            "end_time": {"type": "string", "description": "종료 시각 HH:MM (사용자가 말한 경우만)"},
        },
        "required": ["region"],
    },
)
@safe_tool
def get_wave_forecast(region, date=None, start_time=None, end_time=None):
    start_time = start_time or DEFAULT_START
    end_time = end_time or DEFAULT_END

    # 기준 날짜가 없으면 오늘(한국 시간)로 조회하고, 응답에 그 사실을 밝힌다 (F3002)
    date_defaulted = not date
    if date_defaulted:
        from datetime import timedelta, timezone
        date = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")

    if region not in REGIONS:
        return fail(ErrorCode.INVALID_INPUT, f"지원하는 지역은 {', '.join(REGIONS)}입니다.")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except (ValueError, TypeError):
        return fail(ErrorCode.INVALID_INPUT, "날짜는 YYYY-MM-DD 형식이어야 합니다.")
    if not (TIME_RE.match(start_time) and TIME_RE.match(end_time)) or start_time > end_time:
        return fail(ErrorCode.INVALID_INPUT, "시각은 HH:MM 형식이며 시작이 종료보다 빨라야 합니다.")

    spots = [s for s in SPOTS if s["region"] == region]
    params = {
        "latitude": ",".join(str(s["lat"]) for s in spots),
        "longitude": ",".join(str(s["lon"]) for s in spots),
        "hourly": "wave_height,wave_period,wave_direction",
        "timezone": "Asia/Seoul",
        "start_date": date,
        "end_date": date,
    }
    try:
        r = requests.get(URL, params=params, timeout=config.REQUEST_TIMEOUT)
    except requests.RequestException:
        return fail(ErrorCode.HTTP_ERROR, "파고 예보 서버에 연결하지 못했습니다.")

    if r.status_code == 429:
        return fail(ErrorCode.RATE_LIMITED, "파고 예보 호출 한도를 초과했습니다.")
    try:
        body = r.json()
    except ValueError:
        return fail(ErrorCode.PARSE_ERROR, "파고 예보 응답을 해석하지 못했습니다.")
    if r.status_code != 200 or (isinstance(body, dict) and body.get("error")):
        if r.status_code == 400:
            return fail(ErrorCode.INVALID_INPUT,
                        "해당 날짜의 파고 예보를 제공하지 않습니다. 예보 제공 기간(오늘부터 약 일주일) 안의 날짜인지 확인해 주세요.")
        return fail(ErrorCode.HTTP_ERROR, "파고 예보 서버에서 오류가 발생했습니다.")

    items = body if isinstance(body, list) else [body]
    if len(items) != len(spots):
        return fail(ErrorCode.PARSE_ERROR, "파고 예보 응답의 지점 수가 요청과 다릅니다.")

    h0, h1 = int(start_time[:2]), int(end_time[:2])
    result = []
    for spot, item in zip(spots, items):
        h = item.get("hourly")
        if not h:
            return fail(ErrorCode.PARSE_ERROR, "파고 예보 응답에 시간별 값이 없습니다.")
        rows = []
        for i, t in enumerate(h["time"]):
            if h0 <= int(t[11:13]) <= h1:
                rows.append({
                    "time": t[11:16],
                    "wave_height_m": h["wave_height"][i],
                    "wave_period_s": h["wave_period"][i],
                    "wave_direction_deg": h["wave_direction"][i],
                })
        heights = [x["wave_height_m"] for x in rows if x["wave_height_m"] is not None]
        result.append({
            "spot_id": spot["id"],
            "name": spot["name"],
            "beach_num": spot["beach_num"],
            "grid": {"lat": item.get("latitude"), "lon": item.get("longitude")},
            "hourly": rows,
            "max_wave_height_m": max(heights) if heights else None,
        })

    if all(s["max_wave_height_m"] is None for s in result):
        return fail(ErrorCode.NO_DATA, "해당 시간대의 파고 예보 값이 없습니다.")

    return ok({
        "region": region,
        "date": date,
        "window": {"start": start_time, "end": end_time},
        "source": "Open-Meteo Marine",
        "note": "같은 격자를 쓰는 스팟은 파고 예보 값이 동일합니다."
                + (" 조회 날짜를 받지 못해 오늘 날짜로 조회했습니다." if date_defaulted else ""),
        "date_defaulted": date_defaulted,
        "spots": result,
    })