"""state.py 테스트: python -m scripts.test_state"""
from agent.state import cache_key, empty_conditions, merge_conditions, new_state, trim_history

c = empty_conditions()
c, ch = merge_conditions(c, {"date": "2026-11-21", "region": "양양", "level": "초보", "end_by": "14:00"})
assert ch == ["date", "region", "level", "end_by"]
c2, ch = merge_conditions(c, {"region": "포항", "date": None})   # "다른 지역으로"
assert ch == ["region"] and c2["date"] == "2026-11-21" and c2["end_by"] == "14:00"
_, ch = merge_conditions(c2, {"region": "포항"})                 # 같은 값이면 변경 없음
assert ch == []
assert cache_key("t", {"b": 1, "a": 2}) == cache_key("t", {"a": 2, "b": 1})
assert len(trim_history([{"role": "user", "content": str(i)} for i in range(30)])) == 12
s = new_state("s1", "안녕", conditions=c2)
assert s["replan_count"] == 0 and s["conditions"]["region"] == "포항"
print("모든 테스트 통과")