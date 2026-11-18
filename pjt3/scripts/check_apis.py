"""check_apis.py - 서핑 플래너 외부 API 호출 확인 (기획 검증용)

실행:  python check_apis.py
설치:  pip install requests python-dotenv
.env:  DATA_GO_KR_KEY=공공데이터포털 인증키
       KAKAO_REST_API_KEY=카카오 REST API 키
키 값은 화면에 출력하지 않는다.
"""
import math
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

import requests
from dotenv import load_dotenv

load_dotenv()
KST = timezone(timedelta(hours=9))
TIMEOUT = 15

SPOTS = {
    "양양 죽도": (37.9744, 128.7601),
    "양양 인구": (37.9689, 128.7639),
    "양양 기사문": (38.0055, 128.7317),
    "포항 월포": (36.2033, 129.3714),
    "포항 용한": (36.0987, 129.4130),
    "부산 송정": (35.1785, 129.1997),
    "부산 해운대": (35.1589, 129.1617),
    "제주 중문": (33.2448, 126.4116),
    "제주 협재": (33.3945, 126.2400),
}

BEACHES = {
    "양양 죽도": 250,
    "양양 인구": 252,
    "양양 기사문": 267,
    "포항 월포": 273,
    "포항 용한": 276,
    "부산 송정": 305,
    "부산 해운대": 304,
    "제주 중문": 347,
    "제주 협재": 346,
}
BEACH_URL = "http://apis.data.go.kr/1360000/BeachInfoservice"

results = {}


def report(name, status, detail=""):
    results[name] = status
    print(f"[{status}] {name} {detail}".rstrip())


# ---------- 공통 ----------
def to_grid(lat, lon):
    """위경도 -> 기상청 격자(nx, ny). 기상청 공개 변환식."""
    RE, GRID = 6371.00877, 5.0
    SLAT1, SLAT2, OLON, OLAT = 30.0, 60.0, 126.0, 38.0
    XO, YO = 43, 136
    d = math.pi / 180
    re = RE / GRID
    slat1, slat2, olon, olat = SLAT1 * d, SLAT2 * d, OLON * d, OLAT * d
    sn = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(sn)
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5)
    sf = (sf ** sn) * math.cos(slat1) / sn
    ro = math.tan(math.pi * 0.25 + olat * 0.5)
    ro = re * sf / (ro ** sn)
    ra = math.tan(math.pi * 0.25 + lat * d * 0.5)
    ra = re * sf / (ra ** sn)
    theta = lon * d - olon
    if theta > math.pi:
        theta -= 2 * math.pi
    if theta < -math.pi:
        theta += 2 * math.pi
    theta *= sn
    x = int(math.floor(ra * math.sin(theta) + XO + 0.5))
    y = int(math.floor(ro - ra * math.cos(theta) + YO + 0.5))
    return x, y


def vilage_base(now):
    """단기예보 발표시각(02,05,...,23시). 발표 후 반영 지연 15분 고려."""
    t = now - timedelta(minutes=15)
    hours = [h for h in (2, 5, 8, 11, 14, 17, 20, 23) if h <= t.hour]
    if hours:
        return t.strftime("%Y%m%d"), f"{hours[-1]:02d}00"
    y = t - timedelta(days=1)
    return y.strftime("%Y%m%d"), "2300"


def call_datago(url, extra, key_env):
    """공공데이터포털 호출. (items, None) 또는 (None, 실패사유) 반환."""
    key = os.getenv(key_env) or os.getenv("DATA_GO_KR_KEY")
    if not key:
        return None, f"{key_env} 환경변수 없음"
    params = {"serviceKey": unquote(key), "dataType": "JSON", **extra}
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
    except requests.RequestException as e:
        return None, f"요청 실패({type(e).__name__})"
    try:
        j = r.json()
    except ValueError:
        return None, f"JSON 아닌 응답(HTTP {r.status_code}): {r.text[:150]}"
    header = j.get("response", {}).get("header", {})
    if header.get("resultCode") != "00":
        return None, f"resultCode={header.get('resultCode')} {header.get('resultMsg')}"
    items = j["response"].get("body", {}).get("items")
    item_list = items.get("item", []) if isinstance(items, dict) else []
    return item_list, None


# ---------- 1. 기상청 단기예보 ----------
def check_vilage():
    url = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
    base_date, base_time = vilage_base(datetime.now(KST))
    for name, (lat, lon) in SPOTS.items():
        nx, ny = to_grid(lat, lon)
        items, err = call_datago(url, {
            "base_date": base_date, "base_time": base_time,
            "nx": nx, "ny": ny, "numOfRows": 1000, "pageNo": 1,
        }, "DATA_GO_KR_KEY_VILAGE")
        label = f"단기예보 {name}(nx={nx},ny={ny})"
        if err:
            report(label, "FAIL", err)
            continue
        if not items:
            report(label, "FAIL", "결과 없음")
            continue
        cats = sorted({i["category"] for i in items})
        wind = [i["fcstValue"] for i in items if i["category"] == "WSD"][:3]
        wave = [i["fcstValue"] for i in items if i["category"] == "WAV"][:3]
        report(label, "OK", f"항목={cats} 풍속(WSD)={wind} 파고(WAV)={wave or '없음'}")


# ---------- 2. 기상청 해수욕장 날씨 (여름철 한정 의심) ----------
def check_beach():
    url = "http://apis.data.go.kr/1360000/BeachInfoservice/getUltraSrtFcstBeach"
    t = datetime.now(KST) - timedelta(minutes=45)
    if t.minute < 30:
        t -= timedelta(hours=1)
    items, err = call_datago(url, {
        "base_date": t.strftime("%Y%m%d"), "base_time": f"{t:%H}30",
        "beach_num": 1, "numOfRows": 100, "pageNo": 1,
    }, "DATA_GO_KR_KEY_BEACH")
    label = "해수욕장 날씨(초단기예보, beach_num=1)"
    if err:
        report(label, "FAIL", err)
    elif not items:
        report(label, "FAIL", "응답은 왔지만 데이터 없음 (비수기일 가능성)")
    else:
        cats = sorted({i.get("category", "?") for i in items})
        report(label, "OK", f"항목={cats}")

def check_beach_detail():
    now = datetime.now(KST)
    bd, bt = vilage_base(now)
    obs = (now - timedelta(hours=1)).strftime("%Y%m%d%H") + "00"
    today = now.strftime("%Y%m%d")
    for name, num in BEACHES.items():
        tests = [
            ("단기예보", "getVilageFcstBeach", {"base_date": bd, "base_time": bt}),
            ("파고실황", "getWhBuoyBeach", {"searchTime": obs}),
            ("수온실황", "getTwBuoyBeach", {"searchTime": obs}),
            ("조석", "getTideInfoBeach", {"base_date": today}),
        ]
        for label, ep, extra in tests:
            items, err = call_datago(
                f"{BEACH_URL}/{ep}",
                {"beach_num": num, "numOfRows": 100, "pageNo": 1, **extra},
                "DATA_GO_KR_KEY_BEACH")
            tag = f"해변 {label} {name}(beach_num={num})"
            if err:
                report(tag, "FAIL", err)
            elif not items:
                report(tag, "EMPTY", "응답은 왔지만 데이터 없음")
            else:
                report(tag, "OK", str(items[:2])[:200])

# ---------- 3. Open-Meteo Marine (키 없음) ----------
def check_openmeteo():
    url = "https://marine-api.open-meteo.com/v1/marine"
    for name, (lat, lon) in SPOTS.items():
        label = f"Open-Meteo 파고 {name}"
        try:
            r = requests.get(url, params={
                "latitude": lat, "longitude": lon,
                "hourly": "wave_height,wave_period,wave_direction",
                "timezone": "Asia/Seoul", "forecast_days": 2,
            }, timeout=TIMEOUT)
            j = r.json()
        except (requests.RequestException, ValueError) as e:
            report(label, "FAIL", f"요청/파싱 실패({type(e).__name__})")
            continue
        if j.get("error"):
            report(label, "FAIL", j.get("reason", ""))
            continue
        h = j["hourly"]
        total = len(h["time"])
        nulls = sum(1 for v in h["wave_height"] if v is None)
        nine = [(h["time"][i][5:], h["wave_height"][i], h["wave_period"][i])
                for i in range(total) if h["time"][i].endswith("T09:00")]
        status = "OK" if nulls < total else "FAIL"
        report(label, status,
               f"격자=({j['latitude']},{j['longitude']}) null={nulls}/{total} 09시(시각,파고m,주기s)={nine}")


# ---------- 4. 카카오 로컬 ----------
def check_kakao():
    key = os.getenv("KAKAO_REST_API_KEY")
    label = "카카오 로컬 키워드 검색('양양 서핑샵')"
    if not key:
        report(label, "SKIP", "KAKAO_REST_API_KEY 환경변수 없음")
        return
    try:
        r = requests.get(
            "https://dapi.kakao.com/v2/local/search/keyword.json",
            headers={"Authorization": f"KakaoAK {key}"},
            params={"query": "양양 서핑샵", "size": 3}, timeout=TIMEOUT)
    except requests.RequestException as e:
        report(label, "FAIL", f"요청 실패({type(e).__name__})")
        return
    if r.status_code != 200:
        hint = {401: "키 오류", 403: "카카오맵 사용 설정/승인 확인", 429: "쿼터 초과"}.get(r.status_code, "")
        report(label, "FAIL", f"HTTP {r.status_code} {hint}")
        return
    docs = r.json().get("documents", [])
    if not docs:
        report(label, "FAIL", "결과 없음")
        return
    names = [f"{d['place_name']}({d['address_name']})" for d in docs]
    report(label, "OK", f"{names}")


if __name__ == "__main__":
    print("=== 서핑 플래너 API 호출 확인 ===")
    check_vilage()
    check_beach()
    check_beach_detail()
    check_openmeteo()
    check_kakao()
    print("\n=== 요약 ===")
    for k, v in results.items():
        print(f"{v:5} {k}")