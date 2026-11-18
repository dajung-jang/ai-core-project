"""search_places: 카카오 로컬 키워드 검색으로 스팟 주변 서핑샵·숙소·맛집을 조회 (F3004)"""
import requests

import config
from spots import SPOTS
from tools.base import ErrorCode, fail, ok, register_tool, safe_tool

URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
SPOT_BY_ID = {s["id"]: s for s in SPOTS}
SPOT_IDS = list(SPOT_BY_ID)
CATEGORY_QUERY = {"서핑샵": "서핑샵", "숙소": "숙박", "맛집": "맛집"}  # 사용자용 이름 -> 검색어
DEFAULT_RADIUS_M = 5000  # 스팟 중심 반경
DEFAULT_SIZE = 5
MAX_SIZE = 10


@register_tool(
    name="search_places",
    description=(
        "서핑 스팟 주변의 서핑샵·숙소·맛집을 검색한다. "
        "추천한 스팟과 함께 보여줄 보조 정보(장소, 연락처, 거리)가 필요할 때 사용한다. "
        "서핑 가능 여부를 판단하는 데에는 쓰지 않는다(그때는 get_wave_forecast, get_beach_weather를 쓴다). "
        "spot_id에는 앞선 Tool 결과의 spot_id를 넣는다."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spot_id": {"type": "string", "enum": SPOT_IDS, "description": "주변을 검색할 스팟 id"},
            "category": {"type": "string", "enum": list(CATEGORY_QUERY), "description": "찾을 장소 종류"},
            "size": {"type": "integer", "description": "결과 개수 (기본 5, 최대 10)"},
        },
        "required": ["spot_id", "category"],
    },
)
@safe_tool
def search_places(spot_id, category, size=None):
    if spot_id not in SPOT_BY_ID:
        return fail(ErrorCode.INVALID_INPUT, "지원하지 않는 스팟입니다.")
    if category not in CATEGORY_QUERY:
        return fail(ErrorCode.INVALID_INPUT, f"장소 종류는 {', '.join(CATEGORY_QUERY)} 중에서 골라야 합니다.")
    try:
        size = int(size) if size else DEFAULT_SIZE
    except (TypeError, ValueError):
        return fail(ErrorCode.INVALID_INPUT, "결과 개수는 숫자여야 합니다.")
    size = max(1, min(size, MAX_SIZE))

    key = config.KAKAO_REST_API_KEY
    if not key:
        return fail(ErrorCode.MISSING_KEY, "장소 검색 API 키가 설정되지 않았습니다.")

    spot = SPOT_BY_ID[spot_id]
    params = {
        "query": CATEGORY_QUERY[category],
        "x": spot["lon"],
        "y": spot["lat"],
        "radius": DEFAULT_RADIUS_M,
        "sort": "distance",
        "size": size,
    }
    try:
        r = requests.get(URL, headers={"Authorization": f"KakaoAK {key}"}, params=params,
                         timeout=config.REQUEST_TIMEOUT)
    except requests.RequestException:
        return fail(ErrorCode.HTTP_ERROR, "장소 검색 서버에 연결하지 못했습니다.")

    if r.status_code == 401:
        return fail(ErrorCode.AUTH_ERROR, "장소 검색 API 키가 올바르지 않습니다.")
    if r.status_code == 403:
        return fail(ErrorCode.AUTH_ERROR, "장소 검색 API 사용 권한이 없습니다(카카오맵 사용 설정을 확인하세요).")
    if r.status_code == 429:
        return fail(ErrorCode.RATE_LIMITED, "장소 검색 호출 한도를 초과했습니다.")
    if r.status_code == 400:
        return fail(ErrorCode.INVALID_INPUT, "장소 검색 요청 값이 올바르지 않습니다.")
    if r.status_code != 200:
        return fail(ErrorCode.HTTP_ERROR, "장소 검색 서버에서 오류가 발생했습니다.")

    try:
        docs = r.json().get("documents")
    except (ValueError, AttributeError):
        return fail(ErrorCode.PARSE_ERROR, "장소 검색 응답을 해석하지 못했습니다.")
    if docs is None:
        return fail(ErrorCode.PARSE_ERROR, "장소 검색 응답 형식이 예상과 다릅니다.")
    if not docs:
        return fail(ErrorCode.NO_DATA,
                    f"{spot['name']} 반경 {DEFAULT_RADIUS_M // 1000}km 안에서 '{category}' 검색 결과가 없습니다.")

    places = []
    for d in docs:
        dist = d.get("distance")
        places.append({
            "name": d.get("place_name"),
            "address": d.get("road_address_name") or d.get("address_name"),
            "phone": d.get("phone") or None,
            "distance_m": int(dist) if dist and str(dist).isdigit() else None,
            "category_name": d.get("category_name"),
            "place_url": d.get("place_url"),
        })

    return ok({
        "spot_id": spot_id,
        "spot_name": spot["name"],
        "category": category,
        "radius_m": DEFAULT_RADIUS_M,
        "source": "카카오 로컬",
        "places": places,
    })