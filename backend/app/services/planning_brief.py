"""신규 과제 기획 참고서 (DB 와 무관한 순수 함수).

동향(해외·국내 요구) 하나와 그와 가까운 과거 과제의 성과 카드·평가 의견을 받아
1) 관련 과거 과제 요약 (결과 구분·한계·향후 과제·평가 의견)
2) 요구 성능 ↔ 과거 달성 성능 비교
3) 새 기획에 넣을 것 (이어받기·성능 높이기·남은 숙제·평가 의견·국산화·새로 개발·실패 원인 먼저)
를 만든다. 실패·중단·목표 미달 이력은 '실패 원인 먼저' 로 맨 앞에 둔다
(원인을 풀 방법 없이 같은 과제를 다시 기획하지 않도록).
"""
from __future__ import annotations

from app.config import get_settings
from app.services.gap_rules import NearCard
from app.services.scoring import Performance, _norm, performance_fit

# 기획 참고서에 넣을 관련 성과의 유사도 기준 (기본, '덜 비슷한 과제도 보기').
# 임베더마다 점수 폭이 달라 따로 둔다. bge-m3 는 2026-11-17 gap_eval sims 실측:
# 전차·파워팩 동향과 무관한 카드의 중앙 0.43·상위 10% 0.50·0.55 이상 1%, K2 파워팩 카드는 동력 동향에서 0.61~0.74.
BRIEF_SIM = {"hash": (0.45, 0.35), "bge_m3": (0.55, 0.50)}


def brief_min_sim(wide: bool = False) -> float:
    base, loose = BRIEF_SIM.get(get_settings().embedder, BRIEF_SIM["hash"])
    return loose if wide else base

DEMAND_KIND_KO = {
    "ROADMAP": "해외 기술로드맵", "CALL": "해외 공모", "EXPORT_REQ": "수출 요구",
    "DOMESTIC_PLAN": "국내 계획(국방부·방사청)", "UPGRADE": "성능개량 요구", "SUPPLY": "국산화·단종 대응",
}
ISSUE_KO = {"UNRESOLVED_TECH": "미해결 기술", "UNMET_TARGET": "목표 미달", "FOLLOW_UP_NEED": "후속 연구 필요"}
EVAL_KIND_KO = {"RESULT": "결과평가", "INTERIM": "중간평가", "EXPERT": "전문가 의견", "USER": "소요군 의견"}
COMPARATOR_KO = {"GTE": "이상", "LTE": "이하", "EQ": "", "RANGE": "범위"}
WEAK_GRADES = ("미흡", "실패", "불량", "중단")

# 새 기획에 넣을 것: 종류 → (이름, 보여 줄 순서)
SUGGESTION_KINDS = {
    "CAUTION": ("실패 원인 먼저", 0),
    "UPGRADE": ("성능 높이기", 1),
    "RESOLVE": ("남은 숙제 풀기", 2),
    "EVAL": ("평가 의견 반영", 3),
    "LOCALIZE": ("국산화", 4),
    "NEW": ("새로 개발", 5),
    "REUSE": ("이어받기", 6),
}
COMPARE_KO = {"MET": "충족", "SHORT": "부족", "NO_DATA": "과거 자료 없음", "UNIT_DIFF": "단위 달라 확인 필요",
              "TEXT": "서술형 요구 (사람이 판단)"}


def _num(x: float | None) -> str:
    if x is None:
        return "–"
    return f"{x:,.0f}" if float(x).is_integer() else f"{x:,.2f}".rstrip("0").rstrip(".")


def requirement_text(p: dict) -> str:
    """요구 성능을 한 줄로: '최대출력 1,500마력 이상'."""
    unit = p.get("unit") or ""
    if p.get("required_value") is None:
        return p.get("required_text") or ""
    if p.get("comparator") == "RANGE" and p.get("required_max") is not None:
        return f"{_num(p['required_value'])}~{_num(p['required_max'])}{unit}"
    tail = COMPARATOR_KO.get(p.get("comparator") or "GTE", "")
    return f"{_num(p['required_value'])}{unit}{' ' + tail if tail else ''}"


def _unit_ok(a: str | None, b: str | None) -> bool:
    return not a or not b or _norm(a) == _norm(b)


def compare(requirements: list[dict], cards: list[NearCard], card_project: dict[int, dict]) -> list[dict]:
    """요구 성능마다 과거 성과 중 가장 잘 맞는 달성값을 찾아 충족·부족·자료 없음을 판단한다."""
    rows = []
    for req in requirements:
        row = {"metric_name": req["metric_name"], "required": requirement_text(req), "unit": req.get("unit"),
               "status": "NO_DATA", "achieved_value": None, "ratio": None, "card_id": None, "card_title": None,
               "project_id": None, "project_title": None, "note": None}
        if req.get("required_value") is None:
            row["status"] = "TEXT"
        else:
            r = Performance(req["metric_name"], req.get("comparator") or "GTE", req["required_value"],
                            req.get("required_max"), req.get("unit"))
            best = None
            unit_diff: list[str] = []
            for c in cards:
                for p in c.performances:
                    if p.achieved is None or _norm(p.metric_name) != _norm(req["metric_name"]):
                        continue
                    if not _unit_ok(req.get("unit"), p.unit):
                        unit_diff.append(f"{c.title}: {_num(p.achieved)}{p.unit or ''}")
                        continue
                    fit = performance_fit([r], [Performance(p.metric_name, p.comparator, p.achieved, None, p.unit)])
                    ratio = fit.score if fit else None
                    if ratio is not None and (best is None or ratio > best[0]):
                        best = (ratio, c, p)
            if best:
                ratio, c, p = best
                proj = card_project.get(c.card_id, {})
                row.update(status="MET" if ratio >= 1.0 else "SHORT", achieved_value=p.achieved,
                           ratio=round(ratio, 4), card_id=c.card_id, card_title=c.title,
                           project_id=proj.get("project_id"), project_title=proj.get("title"))
            elif unit_diff:
                row.update(status="UNIT_DIFF", note=", ".join(unit_diff))
        row["status_name"] = COMPARE_KO[row["status"]]
        rows.append(row)
    return rows


def _suggest(kind: str, title: str, detail: str, project_ids: list[int] | None = None,
             card_ids: list[int] | None = None) -> dict:
    name, order = SUGGESTION_KINDS[kind]
    return {"kind": kind, "kind_name": name, "order": order, "title": title, "detail": detail,
            "project_ids": sorted(set(project_ids or [])), "card_ids": sorted(set(card_ids or []))}


def build_brief(trend: dict, requirements: list[dict], cards: list[NearCard], projects: dict[int, dict],
                card_project: dict[int, int], evaluations: dict[int, list[dict]],
                issue_threshold: float = 0.45) -> dict:
    """기획 참고서 본문.

    trend         동향 한 건 (overseas_demand 행)
    requirements  동향의 요구 성능 (overseas_demand_performance 행)
    cards         관련 성과 카드 (열람 가능 + 관련도 기준 이상만, 가까운 순)
    projects      과제 id → 과제 정보 (결과 구분·사업·부서 포함)
    card_project  카드 id → 과제 id
    evaluations   과제 id → 평가 의견 목록 (열람 가능한 것만)
    """
    # 1) 과제별로 묶기 (가장 가까운 카드 순서)
    by_project: dict[int, dict] = {}
    for c in cards:
        pid = card_project[c.card_id]
        if pid not in by_project:
            by_project[pid] = {**projects[pid], "similarity": round(c.similarity, 4), "cards": [],
                               "evaluations": evaluations.get(pid, [])}
        by_project[pid]["cards"].append({
            "card_id": c.card_id, "title": c.title, "trl": c.trl, "similarity": round(c.similarity, 4),
            "performances": [{"metric_name": p.metric_name, "target_value": p.target, "achieved_value": p.achieved,
                              "unit": p.unit, "is_achieved": p.is_achieved} for p in c.performances],
            "limits": [{"issue_type": i.issue_type, "issue_type_name": ISSUE_KO.get(i.issue_type, i.issue_type),
                        "description": i.description, "priority": i.priority} for i in c.open_issues],
            "imported_items": c.imported_items,
        })
    project_list = list(by_project.values())

    # 2) 요구 성능 비교
    card_proj_info = {cid: {"project_id": pid, "title": projects[pid]["title"]} for cid, pid in card_project.items()}
    comparison = compare(requirements, cards, card_proj_info)

    # 3) 새 기획에 넣을 것
    out: list[dict] = []
    for pr in project_list:
        pid = pr["project_id"]
        if pr.get("outcome_is_failure"):
            out.append(_suggest("CAUTION", f"‘{pr['title']}’ {pr['outcome_name']} 원인부터 풀기",
                                f"{pr.get('outcome_note') or '원인 기록 없음'}. 이 원인을 어떻게 풀지 기획서에 먼저 적어야 합니다.",
                                [pid]))
        for c in pr["cards"]:
            for p in c["performances"]:
                if p["is_achieved"] is False:
                    got = (f"목표 {_num(p['target_value'])}{p['unit'] or ''} 중 {_num(p['achieved_value'])}{p['unit'] or ''}"
                           if p["target_value"] is not None and p["achieved_value"] is not None else "목표 미달")
                    out.append(_suggest("CAUTION", f"‘{c['title']}’ {p['metric_name']} 목표 미달 이력",
                                        f"{got}에 그쳤습니다. 미달 원인과 개선 방법을 기획서에 넣으세요.",
                                        [pid], [c["card_id"]]))
        for e in pr["evaluations"]:
            if e.get("grade") and any(w in e["grade"] for w in WEAK_GRADES):
                out.append(_suggest("CAUTION", f"‘{pr['title']}’ {EVAL_KIND_KO.get(e['eval_kind'], '평가')} {e['grade']}",
                                    f"{e['opinion']}", [pid]))
            if e.get("suggestion"):
                who = " · ".join(x for x in (e.get("evaluator"), str(e["eval_date"]) if e.get("eval_date") else None) if x)
                out.append(_suggest("EVAL", e["suggestion"],
                                    f"{EVAL_KIND_KO.get(e['eval_kind'], '평가')} 의견 ({pr['title']}{', ' + who if who else ''})",
                                    [pid]))
    for c in cards:
        pid = card_project[c.card_id]
        for i in c.open_issues:  # near_cards 는 해결 안 된 것만 싣는다
            if i.issue_type == "UNMET_TARGET":
                continue  # 목표 미달은 '실패 원인 먼저' 에서 다룬다
            related = i.priority == "HIGH" or (i.similarity is not None and i.similarity >= issue_threshold)
            if related:
                out.append(_suggest("RESOLVE", i.description,
                                    f"{ISSUE_KO.get(i.issue_type, '남은 과제')} · {c.title}", [pid], [c.card_id]))
        if c.imported_items:
            out.append(_suggest("LOCALIZE", f"수입 의존 품목 국산화 검토: {', '.join(c.imported_items)}",
                                f"{c.title}에 수입 품목이 남아 있습니다.", [pid], [c.card_id]))
    for row in comparison:
        if row["status"] == "SHORT":
            out.append(_suggest(
                "UPGRADE", f"{row['metric_name']}: 요구 {row['required']}, 지금까지 최고 "
                           f"{_num(row['achieved_value'])}{row['unit'] or ''} ({round(100 * row['ratio'])}%)",
                f"차이만큼을 새 과제의 성능 목표로 잡으세요. 근거: {row['card_title']}",
                [row["project_id"]], [row["card_id"]]))
        elif row["status"] == "MET":
            out.append(_suggest(
                "REUSE", f"{row['metric_name']}: 이미 달성 ({_num(row['achieved_value'])}{row['unit'] or ''})",
                f"다시 개발하지 말고 ‘{row['project_title']}’ 성과를 이어받는 것으로 기획하세요.",
                [row["project_id"]], [row["card_id"]]))
    missing = [r["metric_name"] for r in comparison if r["status"] == "NO_DATA"]
    if missing:
        out.append(_suggest("NEW", f"과거 자료가 없는 성능: {', '.join(missing)}",
                            "새로 개발하거나 시험으로 확인할 항목으로 넣으세요."))
    if not project_list:
        out.append(_suggest("NEW", "관련된 과거 과제가 없습니다",
                            "이어받을 성과가 없으니 새 과제로 기획하세요. 해외·민간 기술 도입 여부도 함께 검토하세요."))
    # 같은 제목은 한 번만 (여러 카드가 같은 과제를 가리킬 때)
    seen: set[tuple[str, str]] = set()
    uniq = []
    for s in sorted(out, key=lambda s: s["order"]):
        key = (s["kind"], s["title"])
        if key not in seen:
            seen.add(key)
            uniq.append(s)

    counts = {k: sum(1 for r in comparison if r["status"] == k) for k in COMPARE_KO}
    outcome_counts: dict[str, int] = {}
    for pr in project_list:
        name = pr.get("outcome_name") or "결과 미확인"
        outcome_counts[name] = outcome_counts.get(name, 0) + 1
    return {
        "trend": {**trend, "demand_kind_name": DEMAND_KIND_KO.get(trend.get("demand_kind"), trend.get("demand_kind")),
                  "requirements": [{**r, "text": requirement_text(r)} for r in requirements]},
        "projects": project_list,
        "comparison": comparison,
        "suggestions": uniq,
        "summary": {"project_count": len(project_list), "outcomes": outcome_counts,
                    "met": counts["MET"], "short": counts["SHORT"], "no_data": counts["NO_DATA"],
                    "unchecked": counts["UNIT_DIFF"] + counts["TEXT"],
                    "cautions": sum(1 for s in uniq if s["kind"] == "CAUTION")},
    }


def render_markdown(brief: dict) -> str:
    """기획 참고서를 문서로 (기획수요에 붙여 두는 사본)."""
    t = brief["trend"]
    s = brief["summary"]
    lines = [f"# 기획 참고서: {t['title']}", "",
             f"- 동향 종류: {t['demand_kind_name']} · 지역/기관: {t['region']}"
             + (f" · 목표 시기: {t['target_period']}" if t.get("target_period") else ""),
             f"- 요구 내용: {t['requirement']}", ""]
    if t["requirements"]:
        lines += ["## 요구 성능 비교", "", "| 지표 | 요구 | 과거 최고 달성 | 판단 | 근거 과제 |", "|---|---|---|---|---|"]
        for r in brief["comparison"]:
            got = f"{_num(r['achieved_value'])}{r['unit'] or ''}" if r["achieved_value"] is not None else "–"
            lines.append(f"| {r['metric_name']} | {r['required']} | {got} | {r['status_name']} | {r['project_title'] or '–'} |")
        lines.append("")
    lines += ["## 새 기획에 넣을 것", ""]
    for x in brief["suggestions"]:
        lines.append(f"- **[{x['kind_name']}]** {x['title']} — {x['detail']}")
    lines += ["", f"## 관련 과거 과제 {s['project_count']}건", ""]
    for p in brief["projects"]:
        lines.append(f"### {p['title']} ({p['project_no']})")
        lines.append(f"- 결과: {p.get('outcome_name') or '결과 미확인'}"
                     + (f" — {p['outcome_note']}" if p.get("outcome_note") else ""))
        meta = " · ".join(x for x in (p.get("program_name"), p.get("period"), p.get("department")) if x)
        if meta:
            lines.append(f"- {meta}")
        if p.get("chain"):
            lines.append("- 자료: " + " · ".join(f"{st['name']} {'있음' if st['documents'] else '없음'}" for st in p["chain"]))
        for c in p["cards"]:
            lines.append(f"- 성과: {c['title']}" + (f" (기술성숙도 {c['trl']}단계)" if c["trl"] else ""))
            for lim in c["limits"]:
                lines.append(f"  - 한계·향후 과제 [{lim['issue_type_name']}] {lim['description']}")
        for e in p["evaluations"]:
            lines.append(f"- {EVAL_KIND_KO.get(e['eval_kind'], '평가')}"
                         + (f" ({e['grade']})" if e.get("grade") else "") + f": {e['opinion']}"
                         + (f" / 권고: {e['suggestion']}" if e.get("suggestion") else ""))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
