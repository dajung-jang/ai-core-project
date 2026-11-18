"""모든 Tool이 같은 형식으로 성공/실패를 반환하는 공통 모듈 (F3001, NF3003)"""
import functools


class ErrorCode:
    MISSING_KEY = "MISSING_KEY"      # 환경변수에 키가 없음
    INVALID_INPUT = "INVALID_INPUT"  # 입력 파라미터가 잘못됨
    AUTH_ERROR = "AUTH_ERROR"        # 키 오류, 승인 전 키
    RATE_LIMITED = "RATE_LIMITED"    # 호출 한도 초과
    HTTP_ERROR = "HTTP_ERROR"        # 연결 실패, 타임아웃, 비정상 상태코드
    NO_DATA = "NO_DATA"              # 응답은 왔지만 결과 없음
    PARSE_ERROR = "PARSE_ERROR"      # 응답 형식이 예상과 다름
    UNKNOWN = "UNKNOWN"              # 그 밖의 예외


# 다시 시도해도 결과가 같은 실패: 재계획하지 않고 바로 안내한다 (2.4)
NON_RETRYABLE = {ErrorCode.MISSING_KEY, ErrorCode.INVALID_INPUT, ErrorCode.AUTH_ERROR}


def ok(data):
    return {"ok": True, "data": data}


def fail(code, message):
    # message는 사용자에게 보여도 되는 짧은 안내문만 쓴다 (NF3002)
    return {"ok": False, "error": {"code": code, "message": message}}


def safe_tool(func):
    """Tool 안에서 예외가 나도 밖으로 던지지 않고 ok=False로 바꿔 반환한다."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            return fail(ErrorCode.UNKNOWN, f"{func.__name__} 처리 중 오류({type(e).__name__})")
    return wrapper


# ---- Tool 레지스트리: Agent에는 이름·설명·입력 스키마만 넘긴다 ----
TOOL_REGISTRY = {}


def register_tool(name, description, parameters):
    """parameters는 JSON Schema 형식의 dict"""
    def deco(func):
        TOOL_REGISTRY[name] = {
            "name": name,
            "description": description,
            "parameters": parameters,
            "func": func,
        }
        return func
    return deco


def tool_specs():
    """LLM에 넘길 Tool 명세 목록 (실행 함수는 제외)"""
    return [
        {"type": "function",
         "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
        for t in TOOL_REGISTRY.values()
    ]