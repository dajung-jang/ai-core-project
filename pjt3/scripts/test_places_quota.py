"""search_places 의 실패 응답 분류 테스트 (네트워크 없음): python -m scripts.test_places_quota"""
import config
config.KAKAO_REST_API_KEY = "dummy"
import tools.places as pl


class R:
    def __init__(self, status, body=None):
        self.status_code, self._b = status, body
    def json(self):
        if self._b is None:
            raise ValueError()
        return self._b


def run(resp):
    pl.requests.get = lambda *a, **k: resp
    return pl.search_places("yy_jukdo", "숙소")


cases = [
    (R(400, {"code": -10, "msg": "API limit has been exceeded."}), "RATE_LIMITED"),   # 쿼터 초과 (400 + -10)
    (R(429, {}), "RATE_LIMITED"),
    (R(400, {"errorType": "InvalidArgument"}), "INVALID_INPUT"),                     # 진짜 입력 오류
    (R(400, None), "INVALID_INPUT"),
    (R(401, {}), "AUTH_ERROR"),
    (R(200, {"documents": []}), "NO_DATA"),
]
for resp, code in cases:
    got = run(resp)
    assert not got["ok"] and got["error"]["code"] == code, (resp.status_code, got)
print("모든 테스트 통과")