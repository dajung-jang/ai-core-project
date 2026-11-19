import os
from dotenv import load_dotenv

load_dotenv()

DATA_GO_KR_KEY_BEACH = os.getenv("DATA_GO_KR_KEY_BEACH")
DATA_GO_KR_KEY_VILAGE = os.getenv("DATA_GO_KR_KEY_VILAGE")
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY")
GMS_KEY = os.getenv("GMS_KEY")
GMS_BASE_URL = os.getenv("GMS_BASE_URL")
LLM_MODEL = os.getenv("LLM_MODEL")

REQUEST_TIMEOUT = 15
MAX_REPLAN = 3                 # NF3004 재계획 상한
FORECAST_OBS_GAP_WARN_M = 0.5  # 예보-실측 파고 차이 경고 기준(제안값)

# 실력별 파고·풍속 상한
# 출처: koreacharts 서핑 정보(파고 0.3~0.8m, 풍속 5m/s), Sonuby·Destination NSW(초보 0.3~0.6m)
LEVEL_LIMITS = {
    "초보": {"wave_min_m": 0.3, "wave_caution_m": 0.6, "wave_max_m": 0.8, "wind_max_ms": 5.0},
}

SESSION_HOURS = 2  # 서핑 1회 소요 시간 가정(시간). '늦어도 몇 시에 시작'을 역산할 때 사용

DB_PATH = os.getenv("DB_PATH", "surf_planner.db")  # SQLite 파일 위치 (.gitignore의 *.db에 걸림)