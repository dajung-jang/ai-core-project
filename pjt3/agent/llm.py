"""LLM 호출 래퍼 (GMS, OpenAI 호환)"""
from openai import OpenAI

import config

_client = None


def chat(messages, **kwargs):
    """메시지를 보내 응답 텍스트를 돌려준다. 실패하면 예외가 그대로 올라간다."""
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.GMS_KEY, base_url=config.GMS_BASE_URL,
                         timeout=config.REQUEST_TIMEOUT * 4)
    r = _client.chat.completions.create(model=config.LLM_MODEL, messages=messages, **kwargs)
    return r.choices[0].message.content or ""