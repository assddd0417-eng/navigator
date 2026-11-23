"""선정 가능성(적합도). 공고 평가항목·배점을 D-STATE 영역 점수와 상담 내용으로 평가한다.

  역량 항목(CAPABILITY): 연결한 D-STATE 영역 점수 평균 70↑ 충분 / 40~69 부분 / 40↓ 미흡
  사업 목적(PURPOSE): 상담 애로사항·관심분야와 공고 목적·개요의 관련도 (높음 충분 / 보통 부분 / 낮음 미흡)
  신청서 기반(APPLICATION): 상담 단계에서는 평가하지 않음
  점수 = Σ(배점 × 충족도[충분 100 · 부분 50 · 미흡 0%]) ÷ 평가한 배점 합 × 100 + 우대 가점 (100 에서 자름)
  등급 = 상 70↑ / 중 50~69 / 하 50↓
평가한 항목이 없으면 적합도를 내지 않는다 (근거 없는 판단 차단).
경계값과 부분 충족 비율은 판정기준 설정 (services/criteria.py) 을 따른다. 아래 값은 기본값이다.
"""
from __future__ import annotations

from app.services.dstate import AREA_KO, AREA_TASK

LEVEL_RATIO = {"FULL": 1.0, "PARTIAL": 0.5, "LOW": 0.0}
LEVEL_KO = {"FULL": "충분", "PARTIAL": "부분", "LOW": "미흡"}
KIND_KO = {"CAPABILITY": "역량", "PURPOSE": "사업 목적", "APPLICATION": "신청서 기반"}
GRADE_HIGH, GRADE_MID = 70, 50
DEFAULT = {"capability_full": 70, "capability_partial": 40, "grade_high": GRADE_HIGH, "grade_mid": GRADE_MID,
           "partial_ratio": 50}


def capability_level(score: float, c: dict = DEFAULT) -> str:
    return "FULL" if score >= c["capability_full"] else "PARTIAL" if score >= c["capability_partial"] else "LOW"


def grade(score: float, c: dict = DEFAULT) -> str:
    return "상" if score >= c["grade_high"] else "중" if score >= c["grade_mid"] else "하"


def _score(items: list[dict], bonus: float, c: dict = DEFAULT) -> float | None:
    rated = [x for x in items if x["level"]]
    total = sum(x["points"] for x in rated)
    if not total:
        return None
    ratio = {**LEVEL_RATIO, "PARTIAL": c["partial_ratio"] / 100}
    return min(100.0, sum(x["points"] * ratio[x["level"]] for x in rated) / total * 100 + bonus)


def evaluate(items: list[dict], area_scores: dict[str, int], purpose: dict | None,
             bonus: list[dict], criteria: dict | None = None) -> dict:
    """items: announcement_eval_item 행. purpose: {"similarity", "level"} 또는 None(상담 내용 없음).
    bonus: 충족한 우대 요건 [{"description", "points"}]. criteria: 판정기준 설정 (없으면 기본값)."""
    c = {**DEFAULT, **(criteria or {})}
    out = []
    for it in items:
        row = {"id": it["id"], "name": it["name"], "points": float(it["points"]), "kind": it["kind"],
               "kind_label": KIND_KO[it["kind"]], "areas": list(it["areas"] or []), "level": None,
               "level_label": "-", "basis": "", "source_quote": it.get("source_quote")}
        if it["kind"] == "CAPABILITY":
            vals = [area_scores[a] for a in row["areas"]]
            avg = sum(vals) / len(vals)
            row["level"] = capability_level(avg, c)
            parts = "·".join(f"{AREA_KO[a]} {area_scores[a]}점" for a in row["areas"])
            row["basis"] = f"D-STATE {parts}" + (f" (평균 {avg:.0f}점)" if len(vals) > 1 else "")
            row["area_avg"] = round(avg)
        elif it["kind"] == "PURPOSE":
            if purpose is None:
                row["basis"] = "상담 내용이 없어 평가하지 않음"
            else:
                row["level"] = purpose["level"]
                row["basis"] = (f"상담 내용과 사업 목적 비교: {purpose['reason']}" if purpose.get("reason")
                                else f"상담 내용과 사업 목적 관련도 {purpose['label']} ({purpose['similarity']:.0%})")
        else:
            row["basis"] = "신청서 기반 항목으로 상담 단계 평가 제외"
        row["level_label"] = LEVEL_KO.get(row["level"], "-")
        out.append(row)

    bonus_pts = sum(b["points"] for b in bonus)
    score = _score(out, bonus_pts, c)
    result = {"items": out, "bonus": bonus, "bonus_points": bonus_pts,
              "evaluated_points": sum(x["points"] for x in out if x["level"]),
              "total_points": sum(x["points"] for x in out)}
    if score is None:
        return {**result, "score": None, "grade": None, "grade_label": "평가 기준 없음", "hints": []}
    g = grade(score, c)
    result.update(score=round(score), grade=g, grade_label=f"{g}({round(score)}점)",
                  hints=hints(out, bonus_pts, round(score), area_scores, c))
    return result


def hints(items: list[dict], bonus: float, current: int, area_scores: dict[str, int],
          c: dict = DEFAULT) -> list[dict]:
    """부분·미흡 역량 항목을 '충분'으로 올렸을 때 적합도와 보완과제."""
    out = []
    for x in items:
        if x["kind"] != "CAPABILITY" or x["level"] == "FULL":
            continue
        trial = [{**y, "level": "FULL"} if y is x else y for y in items]
        after = round(_score(trial, bonus, c) or 0)
        if after <= current:
            continue
        weakest = min(x["areas"], key=lambda a: area_scores[a])
        out.append({"item": x["name"], "after_score": after, "after_grade": grade(after, c),
                    "task": AREA_TASK[weakest],
                    "text": f"{x['name']} '충분' 시 적합도 {grade(after, c)}({after}점). 보완: {AREA_TASK[weakest]}"})
    return sorted(out, key=lambda h: -h["after_score"])
