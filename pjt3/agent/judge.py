"""제약 판단: 규칙과 수식만 사용한다 (LLM 호출 없음)"""
from datetime import datetime, timedelta

import config

FIT, CAUTION, UNFIT, UNKNOWN = "적합", "주의", "부적합", "판정 불가"
GRADE_ORDER = {FIT: 0, CAUTION: 1, UNFIT: 2, UNKNOWN: 3}
TARGET_WAVE_M = 0.45  # 같은 등급일 때 이 값에 가까운 파고를 우선


def judge_spot(spot_id, name, wave_max_m, wind_max_ms, observed_wave_m=None, level="초보"):
    """한 스팟을 판정해 {"grade", "reasons", "warnings", ...} 를 돌려준다."""
    lim = config.LEVEL_LIMITS.get(level)
    base = {"spot_id": spot_id, "name": name, "wave_max_m": wave_max_m,
            "wind_max_ms": wind_max_ms, "observed_wave_m": observed_wave_m,
            "reasons": [], "warnings": []}
    if lim is None:
        return {**base, "grade": UNKNOWN, "reasons": [f"'{level}' 레벨의 판단 기준이 없습니다."]}
    if wave_max_m is None or wind_max_ms is None:
        missing = [n for n, v in (("파고", wave_max_m), ("풍속", wind_max_ms)) if v is None]
        return {**base, "grade": UNKNOWN, "reasons": [f"{'·'.join(missing)} 값을 확인하지 못했습니다."]}

    unfit, caution = [], []
    if wave_max_m > lim["wave_max_m"]:
        unfit.append(f"파고 {wave_max_m:.2f}m가 기준({lim['wave_max_m']}m)보다 높음")
    elif wave_max_m > lim["wave_caution_m"]:
        caution.append(f"파고 {wave_max_m:.2f}m가 {lim['wave_caution_m']}m를 넘어 주의 필요")
    elif wave_max_m < lim["wave_min_m"]:
        caution.append(f"파고 {wave_max_m:.2f}m로 파도가 약함")
    if wind_max_ms > lim["wind_max_ms"]:
        unfit.append(f"풍속 {wind_max_ms:.1f}m/s가 기준({lim['wind_max_ms']}m/s)보다 강함")

    warnings = []
    if observed_wave_m is not None and abs(wave_max_m - observed_wave_m) >= config.FORECAST_OBS_GAP_WARN_M:
        warnings.append(f"예보 파고({wave_max_m:.2f}m)와 현재 실측({observed_wave_m:.2f}m) 차이가 커서 "
                        "예보 신뢰도 낮음, 현장 확인 필요")

    if unfit:
        grade, reasons = UNFIT, unfit
    elif caution:
        grade, reasons = CAUTION, caution
    else:
        grade = FIT
        reasons = [f"파고 {wave_max_m:.2f}m, 풍속 {wind_max_ms:.1f}m/s로 기준 이내"]
    return {**base, "grade": grade, "reasons": reasons, "warnings": warnings}


def rank(judgments):
    """후보(부적합·판정 불가 제외)를 좋은 순서로 정렬해 (후보, 제외) 로 돌려준다."""
    cands = [j for j in judgments if j["grade"] in (FIT, CAUTION)]
    excluded = [j for j in judgments if j["grade"] not in (FIT, CAUTION)]
    cands.sort(key=lambda j: (GRADE_ORDER[j["grade"]], j["wind_max_ms"],
                              abs(j["wave_max_m"] - TARGET_WAVE_M)))
    return cands, excluded


def latest_start(end_by, session_hours=None):
    """종료 제한 시각(HH:MM)에서 서핑 시간을 빼 '늦어도 시작해야 하는 시각'을 구한다."""
    hours = session_hours or config.SESSION_HOURS
    t = datetime.strptime(end_by, "%H:%M") - timedelta(hours=hours)
    return t.strftime("%H:%M")