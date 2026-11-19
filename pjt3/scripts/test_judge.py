"""judge.py 단위 테스트 (API 호출 없음): python -m scripts.test_judge"""
from agent import judge as J

# 지금까지 실제로 받은 값: 양양 3곳 파고 최대 0.82m, 풍속 6.7~6.8m/s
for sid, w, wind in [("yy_jukdo", 0.82, 6.7), ("yy_ingu", 0.82, 6.7), ("yy_gisamun", 0.82, 6.8)]:
    assert J.judge_spot(sid, sid, w, wind)["grade"] == J.UNFIT

cases = [
    (0.45, 3.0, J.FIT), (0.6, 5.0, J.FIT), (0.7, 3.0, J.CAUTION), (0.2, 3.0, J.CAUTION),
    (0.9, 3.0, J.UNFIT), (0.45, 5.1, J.UNFIT), (None, 3.0, J.UNKNOWN), (0.45, None, J.UNKNOWN),
]
for w, wind, expect in cases:
    got = J.judge_spot("x", "x", w, wind)["grade"]
    assert got == expect, (w, wind, got, expect)

assert J.judge_spot("x", "x", 1.2, 3.0, observed_wave_m=0.4)["warnings"]       # 차이 0.8 -> 경고
assert not J.judge_spot("x", "x", 0.5, 3.0, observed_wave_m=0.4)["warnings"]   # 차이 0.1 -> 없음
assert J.judge_spot("x", "x", 0.5, 3.0, level="상급")["grade"] == J.UNKNOWN

js = [J.judge_spot("a", "a", 0.7, 2.0), J.judge_spot("b", "b", 0.5, 4.0),
      J.judge_spot("c", "c", 0.45, 3.0), J.judge_spot("d", "d", 1.0, 3.0)]
c, e = J.rank(js)
assert [x["spot_id"] for x in c] == ["c", "b", "a"] and [x["spot_id"] for x in e] == ["d"]
assert J.latest_start("14:00") == "12:00"
print("모든 테스트 통과")