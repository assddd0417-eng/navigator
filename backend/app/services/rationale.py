"""추천 연계이유·개발필요사항 문장 생성.

PoC 기본은 템플릿 기반이다. LLM 으로 바꿀 때는 같은 시그니처의 생성기를 만들어
matching.run_demand_matching 에 넘기면 된다 (근거 문장은 반드시 recommendation_evidence 에 연결된 원문 범위 안에서).
"""
from __future__ import annotations

from typing import Protocol

from app.services.scoring import CardCandidate, CriterionScore, DemandContext

LINKAGE_KO = {"FOLLOW_UP": "후속형", "ADVANCEMENT": "고도화형", "TRANSITION": "전환형",
              "CONVERGENCE": "융합형", "UTILIZATION": "활용형", "COMMERCIALIZATION": "사업화형"}


class RationaleGenerator(Protocol):
    def single(self, linkage: str, card: CardCandidate, demand: DemandContext,
               scores: dict[str, CriterionScore], reason: str) -> tuple[str, str | None]: ...

    def convergence(self, cards: list[tuple[CardCandidate, str, float]], demand: DemandContext) -> tuple[str, str | None]: ...


class TemplateRationale:
    def single(self, linkage, card, demand, scores, reason):
        tech = scores["TECH"]
        text = (f"[{LINKAGE_KO[linkage]}] 성과카드 '{card.title}' 이(가) 수요 '{demand.title}' 와 "
                f"기술 유사도 {tech.score:.2f} ({tech.method}). {reason}. "
                f"TRL 적합도 {scores['TRL'].score:.2f}, 성능 적합도 {scores['PERFORMANCE'].score:.2f}.")
        needs: list[str] = []
        if linkage == "FOLLOW_UP" and card.open_issues:
            hit = card.hits.get("OPEN_ISSUE")
            issue = card.open_issues.get(hit.source_id) if hit and hit.source_id else None
            needs.append(f"미해결 기술 후속 개발: {issue or next(iter(card.open_issues.values()))}")
        for gap in scores["PERFORMANCE"].detail.get("gaps") or []:
            needs.append(f"성능 향상 필요 — {gap}")
        trl = scores["TRL"].detail
        if trl and trl.get("trl") is not None and trl.get("min") is not None and trl["trl"] < trl["min"]:
            needs.append(f"기술성숙도 향상 필요 (TRL {trl['trl']} → {trl['min']} 이상)")
        if linkage == "TRANSITION":
            needs.append("적용 대상 체계·환경에 맞춘 적합성 검증")
        if linkage == "UTILIZATION":
            needs.append("추가 개발 없이 시험·실증 계획 수립")
        if linkage == "COMMERCIALIZATION":
            needs.append("관련 기업·품목 관계 확인 및 사업화 가능성 검토")
        return text, "\n".join(needs) or None

    def convergence(self, cards, demand):
        parts = ", ".join(f"'{c.title}'({element}, {sim:.2f})" for c, element, sim in cards)
        text = f"[융합형] 수요 '{demand.title}' 의 기술요소를 성과 {len(cards)}건이 나누어 충족: {parts}."
        return text, "성과 간 인터페이스 정의 및 통합 시험 필요"
