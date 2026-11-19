"""save: 추천한 스팟을 계획으로 저장한다 (F3015). LLM 없이 규칙으로 처리한다."""
from agent.nodes import effective_end, traced
from events import bus
from store import db
from tools import wave


def _val(v, fmt):
    return "-" if v is None else fmt.format(v)


@traced("save")
def save(state):
    sid = state["session_id"]
    target = state["save_target"]
    c = state.get("last_conditions") or state["conditions"]
    start = c.get("start_time") or wave.DEFAULT_START
    end = effective_end(c) or wave.DEFAULT_END  # 추천 때 확인한 시간대를 그대로 계획 시간으로 쓴다
    note = (f"{c.get('level') or '초보'} 기준 {target['grade']} "
            f"(최대 파고 {_val(target.get('wave_max_m'), '{:.2f}m')}, "
            f"최대 풍속 {_val(target.get('wind_max_ms'), '{:.1f}m/s')})")
    try:
        plan, overlaps = db.save_plan(target["spot_id"], target["name"], c["date"], start, end, note)
    except ValueError as e:
        return {"answer": f"계획을 저장하지 못했어요. {e}", "_end_payload": {"saved": False}}
    except Exception:
        bus.emit(sid, bus.ERROR, {"step": "save", "error": "DB"})
        return {"answer": "계획을 저장하지 못했어요. 잠시 후 다시 시도해 주세요.", "_end_payload": {"saved": False}}

    lines = [f"계획을 저장했어요 (#{plan['id']})",
             f"- 장소: {plan['spot_name']}",
             f"- 날짜: {plan['date']}",
             f"- 시간: {plan['start_time']}~{plan['end_time']} (추천 때 확인한 시간대예요. 계획 관리 화면에서 고칠 수 있어요)",
             f"- 판단: {plan['note']}"]
    if overlaps:
        lines.append("\n⚠ 같은 날 시간이 겹치는 계획이 있어요. 저장은 되어 있어요.")
        lines += [f"- #{o['id']} {o['spot_name']} {o['start_time']}~{o['end_time']}" for o in overlaps]
    bus.emit(sid, bus.PLAN_SAVED, {"plan_id": plan["id"], "spot_id": plan["spot_id"], "date": plan["date"],
                                   "start_time": plan["start_time"], "end_time": plan["end_time"],
                                   "overlap_ids": [o["id"] for o in overlaps]})
    return {"answer": "\n".join(lines), "_end_payload": {"saved": True, "plan_id": plan["id"],
                                                          "overlaps": len(overlaps)}}