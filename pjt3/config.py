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
LEVEL_LIMITS = {}              # 실력별 파고·풍속 상한: 2회차 서핑 문서 근거로 채움