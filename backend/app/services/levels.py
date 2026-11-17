"""관련도 높음/보통/낮음 경계.

유사도(임베딩 코사인)는 임베더마다 값의 폭이 달라 경계를 따로 둔다. 검증 데이터(docs/navigator_eval.md) 기준:
  hash   정답 기업 중앙값 .29, 나머지 최대 .22
  bge-m3 정답 기업 최소 .55·중앙값 .65, 나머지 중앙값 .45·상위 10% .53
"""
from __future__ import annotations

from app.config import get_settings

SIM_LEVELS = {"hash": (0.45, 0.25), "bge_m3": (0.60, 0.53)}


def sim_levels() -> tuple[float, float]:
    s = get_settings()
    high, mid = SIM_LEVELS.get(s.embedder, SIM_LEVELS["hash"])
    return s.navigator_fit_high or high, s.navigator_fit_mid or mid
