"""get_beach_weather: 기상청 전국 해수욕장 날씨 조회서비스 (F3003)
- 단기예보(getVilageFcstBeach): 풍속·풍향·기온·강수 예보
- 파고(getWhBuoyBeach)·수온(getTwBuoyBeach): 현재 실측값 (오늘 날짜를 조회할 때만)
"""
import math
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

import requests

import config
from spots import SPOTS
from tools.base import ErrorCode, fail, ok, register_tool, safe_tool

BASE_URL = "http://apis.data.go.kr/1360000/BeachInfoservice"
KST = timezone(timedelta(hours=9))
DEFAULT_START = "06:00"  # 시각을 말하지 않았을 때의 기본 조회 시간대
DEFAULT_END = "12:00"
SPOT_IDS = [s["id"] for s in SPOTS]
SPOT_BY_ID = {s["id"]: s for s in SPOTS}
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
MISSING = 900  # 가이드: +900 이상, -900 이하 값은 결측

# 공공데이터포털 resultCode -> (실패 코드, 사용자 안내문)
CODE_MAP = {
    "03": (ErrorCode.NO_DATA, "해당 해변의 날씨 데이터가 없습니다."),
    "22": (ErrorCode.RATE_LIMITED, "해변 날씨 호출 한도를 초과했습니다."),
    "20": (ErrorCode.AUTH_ERROR, "해변 날씨 API 접근이 거부되었습니다."),
    "21": (ErrorCode.AUTH_ERROR, "해변 날씨 API 키를 일시적으로 사용할 수 없습니다."),
    "30": (ErrorCode.AUTH_ERROR, "해변 날씨 API 키가 등록되지 않았습니다."),
    "31": (ErrorCode.AUTH_ERROR, "해변 날씨 API 키 사용 기한이 만료되었습니다."),
    "32": (ErrorCode.AUTH_ERROR, "해변 날씨 API에 등록되지 않은 IP입니다."),
    "33": (ErrorCode.AUTH_ERROR, "해변 날씨 API 호출 서명이 올바르지 않습니다."),
    "10": (ErrorCode.INVALID_INPUT, "해변 날씨 요청 값이 올바르지 않습니다."),
    "11": (ErrorCode.INVALID_INPUT, "해변 날씨 요청에 필수 값이 빠졌습니다."),
}


def _num(v):
    """숫자로 바꾸되 결측(±900 이상)이나 숫자가 아니면 None"""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if abs(x) >= MISSING else x


def _vilage_base(now):
    """단기예보 발표 기준 시각(02,05,...,23시). 발표 후 반영 지연 15분을 둔다."""
    t = now - timedelta(minutes=15)
    hours = [h for h in (2, 5, 8, 11, 14, 17, 20, 23) if h <= t.hour]
    if hours:
        return t.strftime("%Y%m%d"), f"{hours[-1]:02d}00"
    y = t - timedelta(days=1)
    return y.strftime("%Y%m%d"), "2300"


def _call(endpoint, params):
    """성공하면 (items, totalCount, None), 실패하면 (None, None, fail 결과)"""
    key = config.DATA_GO_KR_KEY_BEACH
    if not key:
        return None, None, fail(ErrorCode.MISSING_KEY, "해변 날씨 API 키가 설정되지 않았습니다.")
    query = {"serviceKey": unquote(key), "dataType": "JSON", **params}
    try:
        r = requests.get(f"{BASE_URL}/{endpoint}", params=query, timeout=config.REQUEST_TIMEOUT)
    except requests.RequestException:
        return None, None, fail(ErrorCode.HTTP_ERROR, "해변 날씨 서버에 연결하지 못했습니다.")
    try:
        body = r.json()
    except ValueError:
        # 키 오류는 JSON이 아니라 XML로 오는 경우가 있다
        if "SERVICE_KEY" in r.text.upper() or "SERVICE KEY" in r.text.upper():
            return None, None, fail(ErrorCode.AUTH_ERROR, "해변 날씨 API 키가 올바르지 않습니다.")
        return None, None, fail(ErrorCode.PARSE_ERROR, "해변 날씨 응답을 해석하지 못했습니다.")
    resp = body.get("response") if isinstance(body, dict) else None
    if not resp:
        return None, None, fail(ErrorCode.PARSE_ERROR, "해변 날씨 응답 형식이 예상과 다릅니다.")
    code = resp.get("header", {}).get("resultCode")
    if code != "00":
        err_code, msg = CODE_MAP.get(code, (ErrorCode.HTTP_ERROR, "해변 날씨 서버에서 오류가 발생했습니다."))
        return None, None, fail(err_code, msg)
    b = resp.get("body", {})
    items = b.get("items")
    item_list = items.get("item", []) if isinstance(items, dict) else []
    if isinstance(item_list, dict):
        item_list = [item_list]
    return item_list, int(b.get("totalCount") or 0), None


def _fetch_forecast(beach_num):
    """해변 단기예보 전체 항목을 가져온다. (items, 발표시각 문자열, fail 결과)"""
    base_date, base_time = _vilage_base(datetime.now(KST))
    all_items = []
    for page in range(1, 6):
        items, total, err = _call("getVilageFcstBeach", {
            "beach_num": beach_num, "base_date": base_date, "base_time": base_time,
            "numOfRows": 1000, "pageNo": page,
        })
        if err:
            return None, None, err
        all_items += items
        if not items or len(all_items) >= total:
            break
    return all_items, f"{base_date} {base_time}", None


def _fetch_observed(beach_num):
    """현재 파고·수온 실측. 실패하거나 값이 없어도 오류로 보지 않고 None으로 둔다."""
    search_time = (datetime.now(KST) - timedelta(hours=1)).strftime("%Y%m%d%H") + "00"
    out = {"time": None, "wave_height_m": None, "water_temp_c": None}
    for endpoint, field, key in (("getWhBuoyBeach", "wave_height_m", "wh"),
                                 ("getTwBuoyBeach", "water_temp_c", "tw")):
        items, _, err = _call(endpoint, {"beach_num": beach_num, "searchTime": search_time,
                                         "numOfRows": 10, "pageNo": 1})
        if err or not items:
            continue
        item = items[-1]
        out[field] = _num(item.get(key))
        out["time"] = item.get("tm") or out["time"]
    return out


def _build_row(time_hhmm, cats):
    u, v = _num(cats.get("UUU")), _num(cats.get("VVV"))
    wsd = _num(cats.get("WSD"))
    # 풍속은 동서·남북 성분에서 직접 계산한다 (먼 날짜는 WSD가 코드값일 수 있다)
    wind = round(math.hypot(u, v), 1) if u is not None and v is not None else wsd
    return {
        "time": f"{time_hhmm[:2]}:{time_hhmm[2:]}",
        "temp_c": _num(cats.get("TMP")),
        "wind_speed_ms": wind,
        "wind_speed_wsd_raw": cats.get("WSD"),
        "wind_dir_deg": _num(cats.get("VEC")),
        "rain_prob_pct": _num(cats.get("POP")),
        "precip_type_code": _num(cats.get("PTY")),
        "sky_code": _num(cats.get("SKY")),
        "precip_1h": cats.get("PCP"),
        "wave_height_m_coarse": _num(cats.get("WAV")),
    }


@register_tool(
    name="get_beach_weather",
    description=(
        "서핑 후보 스팟의 해변별 바람(풍속·풍향)·기온·강수 예보와 현재 파고·수온 실측값을 조회한다. "
        "get_wave_forecast로 후보 스팟을 얻은 뒤, 그 스팟들의 바람과 날씨가 사용자 조건에 맞는지 판단할 때 사용한다. "
        "spot_ids에는 get_wave_forecast 결과의 spot_id를 넣는다. "
        "시작·종료 시각은 사용자가 말한 경우에만 넣고, 말하지 않았으면 생략한다."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spot_ids": {"type": "array", "items": {"type": "string", "enum": SPOT_IDS},
                         "description": "조회할 스팟 id 목록"},
            "date": {"type": "string", "description": "조회 날짜 YYYY-MM-DD"},
            "start_time": {"type": "string", "description": "시작 시각 HH:MM (사용자가 말한 경우만)"},
            "end_time": {"type": "string", "description": "종료 시각 HH:MM (사용자가 말한 경우만)"},
        },
        "required": ["spot_ids", "date"],
    },
)
@safe_tool
def get_beach_weather(spot_ids, date, start_time=None, end_time=None):
    start_time = start_time or DEFAULT_START
    end_time = end_time or DEFAULT_END

    if not spot_ids or not isinstance(spot_ids, list) or any(s not in SPOT_BY_ID for s in spot_ids):
        return fail(ErrorCode.INVALID_INPUT, "spot_ids는 지원하는 스팟 id의 목록이어야 합니다.")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except (ValueError, TypeError):
        return fail(ErrorCode.INVALID_INPUT, "날짜는 YYYY-MM-DD 형식이어야 합니다.")
    if not (TIME_RE.match(start_time) and TIME_RE.match(end_time)) or start_time > end_time:
        return fail(ErrorCode.INVALID_INPUT, "시각은 HH:MM 형식이며 시작이 종료보다 빨라야 합니다.")

    h0, h1 = int(start_time[:2]), int(end_time[:2])
    target = date.replace("-", "")
    is_today = target == datetime.now(KST).strftime("%Y%m%d")

    results, first_error = [], None
    for sid in spot_ids:
        spot = SPOT_BY_ID[sid]
        entry = {"spot_id": sid, "name": spot["name"], "beach_num": spot["beach_num"]}
        items, base, err = _fetch_forecast(spot["beach_num"])
        if err:
            entry["error"] = err["error"]
            first_error = first_error or err
            results.append(entry)
            continue

        by_time = {}
        for it in items:
            if it.get("fcstDate") == target and h0 <= int(it["fcstTime"][:2]) <= h1:
                by_time.setdefault(it["fcstTime"], {})[it["category"]] = it.get("fcstValue")
        rows = [_build_row(t, by_time[t]) for t in sorted(by_time)]
        if not rows:
            entry["error"] = {"code": ErrorCode.NO_DATA,
                              "message": "해당 날짜·시간대의 해변 예보가 없습니다(이미 지난 시간이거나 단기예보 제공 기간 밖일 수 있습니다)."}
            first_error = first_error or fail(ErrorCode.NO_DATA, entry["error"]["message"])
            results.append(entry)
            continue

        speeds = [r["wind_speed_ms"] for r in rows if r["wind_speed_ms"] is not None]
        entry["forecast_base"] = base
        entry["hourly"] = rows
        entry["max_wind_speed_ms"] = max(speeds) if speeds else None
        entry["observed"] = _fetch_observed(spot["beach_num"]) if is_today else None
        results.append(entry)

    if all("error" in e for e in results):
        return first_error

    return ok({
        "date": date,
        "window": {"start": start_time, "end": end_time},
        "source": "기상청 전국 해수욕장 날씨 조회서비스",
        "note": "실측 파고·수온은 오늘 날짜를 조회할 때만 제공됩니다." if not is_today else
                "observed는 가장 가까운 관측장비의 현재 실측값입니다. 값이 None이면 실측 없음입니다.",
        "spots": results,
    })