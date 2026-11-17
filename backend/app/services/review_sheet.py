"""이어달리기 후보 검토표 · 통합기획 자료 초안.

- 검토표: 열람 가능한 추천 가운데 조건(범위·부서·수요)에 맞는 것을 모아 생성 시점 사본으로 남긴다.
  회의자료를 나중에도 그대로 재현하기 위해서다. 검토 진행 상황(판정)은 볼 때마다 현재 값으로 붙인다.
- 초안: 검토표 사본으로 통합기획 회의용 문서(Markdown)를 만든다. 문장 생성 모델은 쓰지 않는다
  (근거 밖 문장이 섞이지 않게, 연계이유는 추천에 이미 붙은 문장을 그대로 쓴다).
"""
from datetime import date

SCOPE_KO = {
    "COMPLETED_PROJECT_UTILIZATION": "종료과제 활용 후보",
    "CROSS_PROGRAM": "사업트랙·부서 간 연계 후보",
    "DEMAND": "신규 기획수요 대상 후보",
    "CUSTOM": "전체 후보",
}
STATUS_KO = {"GENERATED": "검토 전", "ASSIGNED": "검토 배정", "IN_REVIEW": "검토 중", "NEEDS_INFO": "추가 확인 필요",
             "DECIDED": "판정 완료", "WITHDRAWN": "철회"}
DECISION_KO = {"ADOPT": "채택", "HOLD": "보류", "EXCLUDE": "제외", "NEEDS_INFO": "추가 확인 필요"}
MAX_EVIDENCE = 3

# 최근 매칭 실행(같은 수요·같은 성과 기점의 마지막 성공 실행)의 추천만 후보로 본다. 검증용 실행은 뺀다.
_LATEST_RUNS = """
    SELECT DISTINCT ON (mr.run_type, mr.demand_id, mr.card_id) mr.id
      FROM ax.match_run mr
     WHERE mr.status = 'SUCCEEDED' AND mr.run_type <> 'EVALUATION'
     ORDER BY mr.run_type, mr.demand_id, mr.card_id, mr.id DESC"""


async def select_candidates(conn, uid: int, scope: str, department_id: int | None, demand_id: int | None,
                            per_target: int, limit: int) -> list[int]:
    """조건에 맞는 추천 id (수요·순위 순). 사용자가 볼 수 없는 추천은 넣지 않는다."""
    rows = await (await conn.execute(
        f"""WITH runs AS ({_LATEST_RUNS}),
            c AS (
              SELECT r.id, r.demand_id, r.match_run_id, r.rank,
                     row_number() OVER (PARTITION BY r.match_run_id ORDER BY r.rank) AS n
                FROM ax.recommendation r
                JOIN runs ON runs.id = r.match_run_id
                LEFT JOIN ax.planning_demand pd ON pd.id = r.demand_id
               WHERE r.status <> 'WITHDRAWN' AND NOT r.is_excluded
                 AND ax.can_view_recommendation(%(uid)s, r.id)
                 AND (%(demand)s::bigint IS NULL OR r.demand_id = %(demand)s)
                 AND (%(dept)s::bigint IS NULL
                      OR EXISTS (SELECT 1 FROM ax.recommendation_department rd
                                  WHERE rd.recommendation_id = r.id AND rd.department_id = %(dept)s)
                      OR EXISTS (SELECT 1 FROM ax.recommendation_source_card rsc
                                   JOIN ax.achievement_card ac ON ac.id = rsc.card_id
                                   JOIN ax.project p ON p.id = ac.project_id
                                  WHERE rsc.recommendation_id = r.id AND p.department_id = %(dept)s))
                 AND (%(scope)s <> 'COMPLETED_PROJECT_UTILIZATION'
                      OR EXISTS (SELECT 1 FROM ax.recommendation_source_card rsc
                                   JOIN ax.achievement_card ac ON ac.id = rsc.card_id
                                   JOIN ax.project p ON p.id = ac.project_id
                                  WHERE rsc.recommendation_id = r.id AND p.status_code = 'COMPLETED'))
                 AND (%(scope)s <> 'CROSS_PROGRAM'
                      OR EXISTS (SELECT 1 FROM ax.recommendation_source_card rsc
                                   JOIN ax.achievement_card ac ON ac.id = rsc.card_id
                                   JOIN ax.project p ON p.id = ac.project_id
                                  WHERE rsc.recommendation_id = r.id
                                    AND (p.program_id IS DISTINCT FROM COALESCE(r.target_program_id, pd.target_program_id)
                                         OR p.department_id IS DISTINCT FROM
                                            (SELECT rd.department_id FROM ax.recommendation_department rd
                                              WHERE rd.recommendation_id = r.id AND rd.role = 'OWNER' LIMIT 1)))))
            SELECT id FROM c WHERE n <= %(per)s
             ORDER BY demand_id NULLS LAST, match_run_id, rank
             LIMIT %(limit)s""",
        {"uid": uid, "demand": demand_id, "dept": department_id, "scope": scope, "per": per_target,
         "limit": limit})).fetchall()
    return [r["id"] for r in rows]


async def snapshot(conn, uid: int, rec_id: int) -> tuple[dict, int, list[int]]:
    """추천 하나의 회의자료용 사본, 보안등급 순위, 인용 근거 id 목록."""
    o = await (await conn.execute(
        """SELECT o.recommendation_id, o.rank, o.total_score, o.linkage_type_code, o.linkage_type_name,
                  o.final_linkage_type_code, flt.name_ko AS final_linkage_type_name, o.status,
                  o.final_decision_code, o.demand_id, pd.demand_no, o.demand_title, o.target_program_name,
                  o.development_needs, o.source_cards, o.owner_department, o.evidence_count,
                  o.open_confirmations, rf.rationale
             FROM ax.v_recommendation_overview o
             LEFT JOIN ax.planning_demand pd ON pd.id = o.demand_id
             LEFT JOIN ax.code_linkage_type flt ON flt.code = o.final_linkage_type_code,
                  LATERAL ax.rationale_for_user(%s, o.recommendation_id) rf
            WHERE o.recommendation_id = %s""", (uid, rec_id))).fetchone()
    cards = await (await conn.execute(
        """SELECT ac.id AS card_id, ac.card_no, ac.title, ac.trl, p.project_no, p.title AS project_title,
                  p.status_code AS project_status, p.end_date, d.name AS department, pg.name AS program
             FROM ax.recommendation_source_card rsc
             JOIN ax.achievement_card ac ON ac.id = rsc.card_id
             JOIN ax.project p ON p.id = ac.project_id
             LEFT JOIN ax.department d ON d.id = p.department_id
             LEFT JOIN ax.program pg ON pg.id = p.program_id
            WHERE rsc.recommendation_id = %s ORDER BY rsc.role, ac.id""", (rec_id,))).fetchall()
    depts = await (await conn.execute(
        """SELECT d.name, rd.role FROM ax.recommendation_department rd JOIN ax.department d ON d.id = rd.department_id
            WHERE rd.recommendation_id = %s ORDER BY rd.role DESC, d.name""", (rec_id,))).fetchall()
    companies = await (await conn.execute(
        """SELECT o.name, rc.role FROM ax.recommendation_company rc JOIN ax.organization o ON o.id = rc.organization_id
            WHERE rc.recommendation_id = %s ORDER BY o.name""", (rec_id,))).fetchall()
    # 원문 근거: 만든 사람이 열람할 수 있는 문서만, 관련도 높은 순 몇 건
    evidence = await (await conn.execute(
        """SELECT DISTINCT ON (relevance_score, evidence_id) evidence_id, document_title, section_no,
                  page_start, page_end, left(quote, 200) AS quote, relevance_score
             FROM ax.v_recommendation_evidence
            WHERE recommendation_id = %s AND ax.can_read_document(%s, document_id)
            ORDER BY relevance_score DESC NULLS LAST, evidence_id
            LIMIT %s""", (rec_id, uid, MAX_EVIDENCE))).fetchall()
    final = await (await conn.execute(
        """SELECT rd.decision_code, rd.opinion, u.name AS reviewer FROM ax.review_decision rd
             JOIN ax.app_user u ON u.id = rd.reviewer_id
            WHERE rd.recommendation_id = %s AND rd.is_final ORDER BY rd.id DESC LIMIT 1""", (rec_id,))).fetchone()
    rank = (await (await conn.execute(
        """SELECT GREATEST(
                    COALESCE((SELECT l.level_rank FROM ax.recommendation r JOIN ax.planning_demand d ON d.id = r.demand_id
                                JOIN ax.code_security_level l ON l.code = d.security_code WHERE r.id = %(id)s), 0),
                    COALESCE((SELECT max(l.level_rank) FROM ax.recommendation_source_card rsc
                                JOIN ax.achievement_card ac ON ac.id = rsc.card_id
                                JOIN ax.code_security_level l ON l.code = ac.security_code
                               WHERE rsc.recommendation_id = %(id)s), 0)) AS r""", {"id": rec_id})).fetchone())["r"]
    snap = {
        **{k: o[k] for k in ("recommendation_id", "rank", "linkage_type_code", "linkage_type_name",
                             "final_linkage_type_code", "final_linkage_type_name", "status", "final_decision_code",
                             "demand_id", "demand_no", "demand_title", "target_program_name", "development_needs",
                             "owner_department", "evidence_count", "open_confirmations", "rationale")},
        "total_score": float(o["total_score"]),
        "source_cards": [{**c, "end_date": c["end_date"].isoformat() if c["end_date"] else None} for c in cards],
        "owner_departments": [d["name"] for d in depts if d["role"] == "OWNER"],
        "collab_departments": [d["name"] for d in depts if d["role"] != "OWNER"],
        "companies": [c["name"] for c in companies],
        "evidence": [{**e, "relevance_score": float(e["relevance_score"]) if e["relevance_score"] is not None else None}
                     for e in evidence],
        "final_decision": dict(final) if final else None,
    }
    return snap, rank, [e["evidence_id"] for e in evidence]


def _one_line(text: str | None) -> str:
    return "; ".join(x.strip() for x in (text or "").splitlines() if x.strip())


def _cell(text: str) -> str:
    return _one_line(text).replace("|", "/")


def _cards_text(s: dict) -> str:
    return ", ".join(f"{c['title']}({c['project_no']})" for c in s["source_cards"])


def _linkage(s: dict) -> str:
    if s.get("final_linkage_type_name") and s["final_linkage_type_code"] != s["linkage_type_code"]:
        return f"{s['final_linkage_type_name']} (추천 {s['linkage_type_name']})"
    return s["linkage_type_name"]


def _decision(live: dict) -> str:
    if live.get("final_decision_code"):
        return DECISION_KO.get(live["final_decision_code"], live["final_decision_code"])
    return STATUS_KO.get(live.get("status"), live.get("status") or "")


def render_draft(sheet: dict, items: list[dict], decisions: list[dict]) -> tuple[str, dict, list[int]]:
    """검토표 → 통합기획 자료 초안 (Markdown, 구조화 섹션, 인용 근거 id 순서)."""
    snaps = [i["snapshot"] for i in items]
    live = {i["recommendation_id"]: i["live"] for i in items}
    footnotes: list[dict] = []
    fn_index: dict[int, int] = {}

    def cite(ev: dict) -> str:
        if ev["evidence_id"] not in fn_index:
            footnotes.append(ev)
            fn_index[ev["evidence_id"]] = len(footnotes)
        return f"[{fn_index[ev['evidence_id']]}]"

    by_type: dict[str, int] = {}
    for s in snaps:
        by_type[s["linkage_type_name"]] = by_type.get(s["linkage_type_name"], 0) + 1
    decided = sum(1 for s in snaps if live.get(s["recommendation_id"], {}).get("final_decision_code"))
    demands = sorted({s["demand_title"] for s in snaps if s["demand_title"]})
    owners = sorted({d for s in snaps for d in s["owner_departments"]})
    collabs = sorted({d for s in snaps for d in s["collab_departments"]} - set(owners))

    lines = [f"# 통합기획 검토자료: {sheet['title']}", "",
             f"- 작성일: {date.today().isoformat()}",
             f"- 범위: {SCOPE_KO.get(sheet['sheet_scope'], sheet['sheet_scope'])}"
             + (f" / 대상 부서: {sheet['department_name']}" if sheet.get("department_name") else ""),
             f"- 후보 수: {len(snaps)}건 (판정 완료 {decided}건, 담당부서 최종 검토율 "
             f"{round(decided * 100 / len(snaps)) if snaps else 0}%)", "",
             "## 1. 검토 배경", "",
             "기존 R&D 성과를 후속과제·타 사업트랙과 연결할 수 있는 후보를 모았습니다. "
             "아래 후보는 연계검토용이며, 사업 추진 여부와 성과평가는 담당부서와 위원회가 판단합니다.", ""]
    if demands:
        lines += ["대상 신규 기획수요: " + ", ".join(demands), ""]
    lines += ["## 2. 후보 요약", "",
              "| 번호 | 기존 성과 | 연계 대상 | 연계유형 | 종합점수 | 담당부서 | 검토 상태 |",
              "|---|---|---|---|---|---|---|"]
    for n, s in enumerate(snaps, start=1):
        target = s["demand_title"] or s["target_program_name"] or ""
        lines.append(f"| {n} | {_cell(_cards_text(s))} | {_cell(target)} | {_linkage(s)} | {s['total_score']:.2f} | "
                     f"{', '.join(s['owner_departments']) or '미지정'} | {_decision(live.get(s['recommendation_id'], s))} |")
    lines += ["", "연계유형별: " + ", ".join(f"{k} {v}건" for k, v in sorted(by_type.items(), key=lambda x: -x[1])), "",
              "## 3. 후보별 검토 내용", ""]
    for n, s in enumerate(snaps, start=1):
        lv = live.get(s["recommendation_id"], s)
        lines += [f"### 3.{n} {_cards_text(s)} → {s['demand_title'] or s['target_program_name'] or ''}", "",
                  f"- 연계유형: {_linkage(s)} (종합점수 {s['total_score']:.2f})"]
        for c in s["source_cards"]:
            if c["project_status"] == "COMPLETED":
                state = f"{c['end_date']} 종료" if c["end_date"] else "종료"
            else:
                state = "진행 중" if c["project_status"] == "IN_PROGRESS" else ""
            lines.append(f"- 기존 과제: {c['project_title']} ({c['project_no']}"
                         + (f", {state}" if state else "")
                         + (f", 기술성숙도 {c['trl']}" if c["trl"] else "") + f") / {c['department'] or ''}")
        cites = "".join(cite(e) for e in s["evidence"])
        lines.append(f"- 연계이유: {_one_line(s['rationale'])}{(' ' + cites) if cites else ''}")
        if s.get("development_needs"):
            lines.append(f"- 개발 필요사항: {_one_line(s['development_needs'])}")
        lines.append(f"- 담당부서: {', '.join(s['owner_departments']) or '미지정'}"
                     + (f" / 협업부서: {', '.join(s['collab_departments'])}" if s["collab_departments"] else ""))
        if s["companies"]:
            lines.append(f"- 관련 기업 후보 (확정 아님): {', '.join(s['companies'])}")
        if s["open_confirmations"]:
            lines.append(f"- 추가 확인 필요사항: {s['open_confirmations']}건")
        fd = lv.get("final_decision") or s.get("final_decision")
        lines.append(f"- 검토 상태: {_decision(lv)}"
                     + (f" ({fd['reviewer']}: {fd['opinion']})" if fd and fd.get("opinion") else ""))
        lines.append("")
    pending = [n for n, s in enumerate(snaps, start=1) if not live.get(s["recommendation_id"], {}).get("final_decision_code")]
    lines += ["## 4. 회의 상정 사항", ""]
    if pending:
        lines.append(f"- 담당부서 최종 판정이 필요한 후보: {', '.join(f'{n}번' for n in pending)}")
    need_info = [n for n, s in enumerate(snaps, start=1) if s["open_confirmations"]]
    if need_info:
        lines.append(f"- 기업·품목 관계 등 추가 확인이 필요한 후보: {', '.join(f'{n}번' for n in need_info)}")
    if owners:
        lines.append(f"- 담당부서: {', '.join(owners)}" + (f" / 협업 검토 부서: {', '.join(collabs)}" if collabs else ""))
    if not pending and not need_info:
        lines.append("- 모든 후보의 판정이 끝났습니다. 채택 후보의 후속조치를 정합니다.")
    lines.append("")
    if decisions:
        lines += ["## 5. 회의 결정·후속조치", "", "| 결정 | 후속조치 | 담당 | 기한 | 상태 |", "|---|---|---|---|---|"]
        for d in decisions:
            lines.append(f"| {d['decision']} | {d['follow_up_action'] or ''} | {d['owner_dept_name'] or ''} | "
                         f"{d['due_date'] or ''} | {({'OPEN': '진행', 'DONE': '완료', 'DROPPED': '취소'}).get(d['status'], d['status'])} |")
        lines.append("")
    if footnotes:
        lines += ["## 원문 근거", ""]
        for i, e in enumerate(footnotes, start=1):
            page = (f" p.{e['page_start']}" + (f"~{e['page_end']}" if e["page_end"] and e["page_end"] != e["page_start"] else "")
                    if e["page_start"] else "")
            sec = f" {e['section_no']}" if e.get("section_no") else ""
            lines.append(f"[{i}] {e['document_title']}{sec}{page}: \"{e['quote']}\"")
        lines.append("")
    struct = {"scope": sheet["sheet_scope"], "candidates": len(snaps), "decided": decided,
              "by_linkage_type": by_type, "pending": pending, "needs_confirmation": need_info,
              "owner_departments": owners, "collab_departments": collabs}
    return "\n".join(lines), struct, [e["evidence_id"] for e in footnotes]
