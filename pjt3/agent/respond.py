"""respond: 판단 결과를 규칙으로 정리해 최종 응답을 만든다 (F3011). 수치를 LLM이 바꾸지 못하도록 LLM을 쓰지 않는다."""
import config
from agent import judge as J
from agent.review import PLACES_PER_KIND
from agent.nodes import effective_end, traced
from agent.state import cache_key
from tools import wave

DISCLAIMER = ("※ 예보와 실측 자료를 바탕으로 한 참고 정보이며, 현장의 안전 판단을 대신하지 않습니다. "
              "출발 전 현장 상황과 안전 수칙을 직접 확인하세요.")
SOURCES = ("출처: 파고 예보 Open-Meteo Marine(NOAA·ECMWF·DWD·Copernicus), 해변 풍속·수온·실측 파고 기상청, "
           "주변 장소 카카오 로컬")


def _window_text(c):
    start = c.get("start_time") or wave.DEFAULT_START
    end = effective_end(c) or wave.DEFAULT_END
    if not (c.get("start_time") or c.get("end_time") or c.get("end_by")):
        return f"{start}~{end}(시각을 말씀하지 않아 기본 조회 시간대)"
    return f"{start}~{end}"


def _criteria_text(level):
    lim = config.LEVEL_LIMITS[level]
    return (f"{level} 기준: 파고 {lim['wave_min_m']}~{lim['wave_caution_m']}m이고 풍속 {lim['wind_max_ms']:g}m/s 이하면 적합, "
            f"파고 {lim['wave_caution_m']}~{lim['wave_max_m']}m 또는 {lim['wave_min_m']}m 미만이면 주의, "
            f"파고 {lim['wave_max_m']}m 초과 또는 풍속 {lim['wind_max_ms']:g}m/s 초과면 부적합")


def _wetsuit(temp):
    if temp is None:
        return None
    if temp >= 16:
        return f"현재 수온 {temp:g}℃(실측). 수온이 높은 편이라 얇은 웻슈트나 스프링슈트도 고려할 수 있어요."
    if temp >= 13:
        return f"현재 수온 {temp:g}℃(실측). 4/3mm 웻슈트와 부츠를 권장하는 수온대예요(Sonuby 기준)."
    return f"현재 수온 {temp:g}℃(실측). 5/4mm 웻슈트에 부츠·장갑·후드를 권장하는 수온대예요(Sonuby 기준)."


def _fatal_text(err):
    msg = err.get("message", "처리 중 오류가 발생했습니다.")
    if err.get("code") in ("MISSING_KEY", "AUTH_ERROR"):
        msg += "\n.env 파일의 API 키 설정을 확인해 주세요."
    return msg


def _line(j):
    wave_t = "-" if j["wave_max_m"] is None else f"{j['wave_max_m']:.2f}m"
    wind_t = "-" if j["wind_max_ms"] is None else f"{j['wind_max_ms']:.1f}m/s"
    return f"{j['name']} — {j['grade']} (최대 파고 {wave_t}, 최대 풍속 {wind_t})"


def build_answer(state):
    if state.get("fatal_error"):
        return _fatal_text(state["fatal_error"])
    c = state["conditions"]
    level = c.get("level") or "초보"
    tried = state.get("tried_regions", [])
    cands, excluded = state.get("candidates", []), state.get("excluded", [])
    out = []

    if cands:
        out.append(f"{c['date']} {_window_text(c)} · {level} 기준으로 확인한 결과예요.")
        if not c.get("region"):
            out.append(f"지역을 말씀하지 않아 {tried[0]}부터 확인했어요.")
        elif len(tried) > 1:
            out.append(f"요청하신 {tried[0]}은(는) 조건에 맞지 않아 {', '.join(tried[1:])}까지 넓혀 확인했어요.")
        out.append("\n추천")
        for i, j in enumerate(cands, 1):
            out.append(f"{i}. {_line(j)}")
            out += [f"   - {r}" for r in j["reasons"]]
            out += [f"   - ⚠ {w}" for w in j["warnings"]]
        if c.get("end_by"):
            out.append(f"\n{c['end_by']}까지 끝내려면 늦어도 {J.latest_start(c['end_by'])}에는 시작해야 해요"
                       f"(서핑 {config.SESSION_HOURS}시간 기준).")
        tip = _wetsuit(cands[0].get("observed_water_c"))
        if tip:
            out.append(tip)
        # 보조 정보: 1순위 스팟 주변 장소
        for kind in c.get("wants_places", []):
            entry = state["tool_cache"].get(cache_key("search_places", {
                "spot_id": cands[0]["spot_id"], "category": kind, "size": PLACES_PER_KIND}), {})
            if entry.get("ok"):
                out.append(f"\n{cands[0]['name']} 주변 {kind}")
                out += [f"- {p['name']} ({p['address']}, {p['distance_m']}m)" for p in entry["summary"]["places"]]
            else:
                out.append(f"\n{kind} 정보는 불러오지 못했어요.")
    else:
        out.append(f"{c['date']} {_window_text(c)} · {level} 기준으로 {', '.join(tried)}을(를) 확인했지만 "
                   "조건에 맞는 곳을 찾지 못했어요.")
        if state.get("replan_count", 0) >= config.MAX_REPLAN:
            out.append(f"재탐색을 {config.MAX_REPLAN}회까지 했어요.")
        out.append("날짜나 시간대를 바꾸면 다시 확인해 볼 수 있어요. 조건을 조정해 볼까요?")

    if excluded:
        out.append("\n제외한 곳")
        for j in excluded:
            out.append(f"- {j['name']}: " + " / ".join(j["reasons"]))
    out.append("\n판단 기준\n" + _criteria_text(level))
    out.append("파고는 지역 단위 예보라 같은 격자의 스팟은 값이 같아요. 같은 날 먼 시간대는 예보 정확도가 떨어질 수 있어요.")
    out.append("\n" + DISCLAIMER + "\n" + SOURCES)
    return "\n".join(out)


@traced("respond")
def respond(state):
    answer = build_answer(state)
    return {"answer": answer, "_end_payload": {"length": len(answer)}}