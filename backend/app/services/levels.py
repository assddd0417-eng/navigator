"""화면·문장에 점수 대신 쓰는 높음/보통/낮음.

유사도(임베딩 코사인)는 임베더마다 값의 폭이 달라 경계를 따로 둔다. 검증 데이터(docs/navigator_eval.md) 기준:
  hash   정답 기업 중앙값 .29, 나머지 최대 .22
  bge-m3 정답 기업 최소 .55·중앙값 .65, 나머지 중앙값 .45·상위 10% .53
비율형 점수(TRL·성능 충족 등 0~1)는 0.7/0.5 로 나눈다 (화면 ui.tsx fitLevel 과 같음).
"""
from __future__ import annotations

from app.config import get_settings

SIM_LEVELS = {"hash": (0.45, 0.25), "bge_m3": (0.60, 0.53)}
SCORE_LEVELS = (0.7, 0.5)


def sim_levels() -> tuple[float, float]:
    s = get_settings()
    high, mid = SIM_LEVELS.get(s.embedder, SIM_LEVELS["hash"])
    return s.navigator_fit_high or high, s.navigator_fit_mid or mid


def _word(v: float | None, high: float, mid: float) -> str:
    if v is None:
        return "모름"
    return "높음" if v >= high else "보통" if v >= mid else "낮음"


def sim_word(v: float | None) -> str:
    return _word(v, *sim_levels())


def score_word(v: float | None) -> str:
    return _word(v, *SCORE_LEVELS)
