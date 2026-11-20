"""LLM API 호출과 Tool 선택 확인 (2.7 도구 연결 확인)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import OpenAI

import config
from tools.base import ok, register_tool, tool_specs


@register_tool(
    name="get_wave_forecast",
    description=(
        "서핑 후보 지역의 시간별 파고·파주기 예보를 조회한다. "
        "사용자가 날짜와 지역을 말하고 서핑하기 좋은지, 어디서 탈 수 있는지 물을 때 사용한다. "
        "날짜나 지역을 모르면 호출하지 말고 사용자에게 되묻는다."
        "시작·종료 시각은 사용자가 말한 경우에만 넣고, 말하지 않았으면 생략한다."
    ),
    parameters={
        "type": "object",
        "properties": {
            "region": {"type": "string", "enum": ["양양", "포항", "부산", "제주"], "description": "조회할 지역"},
            "date": {"type": "string", "description": "조회 날짜 YYYY-MM-DD"},
            "start_time": {"type": "string", "description": "시작 시각 HH:MM"},
            "end_time": {"type": "string", "description": "종료 시각 HH:MM"},
        },
        "required": ["region", "date"],
    },
)
def _dummy(region, date, start_time=None, end_time=None):
    return ok({})


def main():
    missing = [k for k in ("GMS_KEY", "GMS_BASE_URL", "LLM_MODEL") if not getattr(config, k)]
    if missing:
        print("[FAIL] .env에 값이 없음:", missing)
        return

    client = OpenAI(api_key=config.GMS_KEY, base_url=config.GMS_BASE_URL)

    # 1. 단순 호출
    try:
        r = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "user", "content": "한 단어로 대답해: 안녕"}],
        )
        print("[OK] LLM 호출:", r.choices[0].message.content)
    except Exception as e:
        print("[FAIL] LLM 호출:", type(e).__name__, getattr(e, "status_code", ""))
        return

    # 2. Tool 선택
    system = ("너는 서핑 플래너 Agent다. 오늘은 2026-11-18(수요일)이다. "
              "필요하면 Tool을 사용하고, 조건이 부족하면 사용자에게 되묻는다.")
    cases = [
        ("토요일 오전에 양양에서 초보가 탈 만한 곳 찾아줘, 오후 2시 전엔 나와야 해",
         "get_wave_forecast 호출 (region=양양, date=2026-11-21)"),
        ("서핑하고 싶어", "Tool 호출 없이 되묻기"),
    ]
    for text, expect in cases:
        print("\n요청:", text)
        print("기대:", expect)
        try:
            r = client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
                tools=tool_specs(),
            )
        except Exception as e:
            print("[FAIL] Tool 선택 호출:", type(e).__name__, getattr(e, "status_code", ""))
            continue
        msg = r.choices[0].message
        if msg.tool_calls:
            for tc in msg.tool_calls:
                print("[결과] Tool 선택:", tc.function.name, tc.function.arguments)
        else:
            print("[결과] Tool 호출 없음. 응답:", msg.content)


"""LLM(GMS) 호출만 따로 점검한다: python -m scripts.check_llm"""
import config
from agent import llm

print("GMS_KEY 설정됨:", bool(config.GMS_KEY))
print("GMS_BASE_URL:", config.GMS_BASE_URL)
print("LLM_MODEL:", config.LLM_MODEL)
try:
    print("응답:", llm.chat([{"role": "user", "content": "안녕이라고만 답해줘"}]))
except Exception as e:
    print("오류 종류:", type(e).__name__)
    print("오류 내용:", e)
    
if __name__ == "__main__":
    main()