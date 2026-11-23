"""상담용 지원사업 자격검토. 공고마다 두 가지를 판정한다.

  Q1 신청할 수 있는가: 필수요건(신청자격·신청제한)을 기업정보와 대조. 하나라도 미충족이면 신청 불가
  Q2 선정 가능성(적합도): 평가항목·배점 x D-STATE 영역 점수 + 상담 내용과 사업 목적 (services/fit.py)
판정은 규칙으로 하고, 요건마다 공고문 근거 조항(인용·쪽)을 붙인다. 근거가 없는 요건은 '근거 조항 없음'으로 표시해
담당자가 확인하게 한다. AI 판단을 켜면 공고마다 LLM 을 한 번 불러 서술형 요건을 근거 인용으로 판단하고,
수치 요건은 규칙 결과로 다시 확인한다 (services/ai_judge.py). 결과는 상담 참고자료이며 확정은 담당자가 한다.
"""
from __future__ import annotations

from datetime import date

from psycopg import AsyncConnection

from app.config import get_settings
from app.services import ai_gateway, ai_judge, criteria, dstate, fit, regulation
from app.services.eligibility import RESULT_KO, judge, overall
from app.services.embedding import embed_query
from app.services.levels import sim_levels
from app.services.navigator_embedding import ensure_embeddings
from app.services.navigator_matching import load_announcements, load_companies

Q1_KO = {"ELIGIBLE": "신청 가능", "NEEDS_INFO": "확인 필요", "INELIGIBLE": "신청 불가"}
ORDER = {"ELIGIBLE": 0, "NEEDS_INFO": 1, "INELIGIBLE": 2}


async def _announcement_ids(conn: AsyncConnection, include_closed: bool) -> list[int]:
    states = ["OPEN", "UPCOMING"] + (["CLOSED"] if include_closed else [])
    rows = await (await conn.execute(
        """SELECT id FROM ax.v_announcement WHERE status = 'PUBLISHED' AND receipt_state = ANY(%s)
            ORDER BY receipt_end NULLS LAST, id""", (states,))).fetchall()
    return [r["id"] for r in rows]


async def purpose_fit(conn: AsyncConnection, concern: str | None, ann_ids: list[int]) -> dict[int, dict]:
    """상담 애로사항·관심분야와 공고 목적·개요의 코사인 유사도 최댓값."""
    if not concern or not concern.strip() or not ann_ids:
        return {}
    await ensure_embeddings(conn)   # SQL 로 넣은 공고는 벡터가 없을 수 있음
    q = await embed_query(concern.strip())
    rows = await (await conn.execute(
        """SELECT announcement_id, max(1 - (embedding <=> %s)) AS sim FROM ax.announcement_embedding
            WHERE announcement_id = ANY(%s) AND facet IN ('PURPOSE', 'SUMMARY')
              AND model_id = (SELECT id FROM ax.embedding_model WHERE is_active)
            GROUP BY announcement_id""", (q, ann_ids))).fetchall()
    high, mid = sim_levels()
    out = {}
    for r in rows:
        sim = float(r["sim"])
        level = "FULL" if sim >= high else "PARTIAL" if sim >= mid else "LOW"
        out[r["announcement_id"]] = {"similarity": sim, "level": level,
                                     "label": {"FULL": "높음", "PARTIAL": "보통", "LOW": "낮음"}[level]}
    return out


async def _ann_extra(conn: AsyncConnection, ann_ids: list[int]) -> dict[int, dict]:
    rows = await (await conn.execute(
        """SELECT a.id, a.announcement_no, a.program_name, a.summary, a.support_amount_krw, a.support_period_months,
                  a.receipt_start, a.receipt_end, a.receipt_state, x.company_burden, x.submit_documents,
                  x.body_text, x.program_id, x.series_key, x.requirements_confirmed_at, x.updated_at AS ann_updated_at,
                  p.purpose
             FROM ax.v_announcement a JOIN ax.announcement x ON x.id = a.id
             LEFT JOIN ax.program p ON p.id = x.program_id WHERE a.id = ANY(%s)""",
        (ann_ids,))).fetchall()
    extra = {r["id"]: {**r, "eval_items": [], "bonus": {}, "attachments": []} for r in rows}
    for t in await (await conn.execute(
            """SELECT announcement_id, text_content FROM ax.announcement_attachment
                WHERE announcement_id = ANY(%s) AND parse_status = 'PARSED' AND text_content IS NOT NULL
                ORDER BY id""", (ann_ids,))).fetchall():
        extra[t["announcement_id"]]["attachments"].append(t["text_content"])
    for e in await (await conn.execute(
            "SELECT * FROM ax.announcement_eval_item WHERE announcement_id = ANY(%s) ORDER BY sort_order, id",
            (ann_ids,))).fetchall():
        extra[e["announcement_id"]]["eval_items"].append(e)
    for r in await (await conn.execute(
            "SELECT id, announcement_id, bonus_points FROM ax.announcement_requirement "
            "WHERE announcement_id = ANY(%s) AND bonus_points IS NOT NULL", (ann_ids,))).fetchall():
        extra[r["announcement_id"]]["bonus"][r["id"]] = float(r["bonus_points"])
    return extra


async def review(conn: AsyncConnection, org_id: int, *, concern: str | None = None,
                 announcement_ids: list[int] | None = None, include_closed: bool = False,
                 diagnosis: dict | None = None, user_id: int | None = None) -> dict:
    diagnosis = diagnosis or await dstate.run(conn, org_id, save=False)
    area_scores = {a["code"]: a["score"] for a in diagnosis["areas"]}
    ann_ids = announcement_ids or await _announcement_ids(conn, include_closed)
    if not ann_ids:
        return {"organization_id": org_id, "concern": concern, "results": [], "summary": {k: 0 for k in Q1_KO}}
    org = (await load_companies(conn, [org_id]))[org_id]
    anns = await load_announcements(conn, ann_ids)
    extra = await _ann_extra(conn, ann_ids)
    purpose = await purpose_fit(conn, concern, ann_ids)
    use_ai = ai_gateway.mode() == "llm"
    ai_left = get_settings().ai_judge_max_announcements
    limits_by_prog: dict[int | None, list[dict]] = {}
    crit = await criteria.active(conn)

    results = []
    for ann_id in ann_ids:
        ann = anns.get(ann_id)
        if ann is None:
            continue
        x = extra[ann_id]
        if x["program_id"] not in limits_by_prog:
            limits_by_prog[x["program_id"]] = await regulation.limit_articles(conn, x["program_id"])
        common = regulation.common_requirements(limits_by_prog[x["program_id"]], ann.requirements,
                                                {"id": ann_id, "title": ann.title, "series_key": x["series_key"],
                                                 "program_id": x["program_id"], "program_name": x["program_name"]})
        reqs = ann.requirements + [r for r, _ in common]
        meta_of = {**ann.req_meta, **{r.id: {"type_name": "공통 참여제한", "quote": f"{a['ref']}: {a['body'][:300]}",
                                              "page": None, "regulation": a["ref"]} for r, a in common}}
        checks = [(req, judge(req, org, ann.as_of)) for req in reqs]
        verdict = overall(checks)
        rows = []
        for req, ch in checks:
            meta = meta_of[req.id]
            rows.append({
                "requirement_id": req.id, "req_type_code": req.req_type, "req_type_name": meta["type_name"],
                "description": req.description, "is_mandatory": req.is_mandatory,
                "mandatory_label": "필수" if req.is_mandatory else "우대",
                "result": ch.result, "result_label": RESULT_KO[ch.result], "reason": ch.reason,
                "question": ch.question, "self_declared": ch.self_declared,
                "source_quote": meta["quote"], "source_page": meta["page"],
                "has_basis": bool(meta["quote"]),
                "bonus_points": x["bonus"].get(req.id),
                "regulation_ref": meta.get("regulation"),
            })
        query = " ".join([ann.title] + [r["description"] for r in rows if r["is_mandatory"]] + [concern or ""])
        regs = await regulation.basis_for(conn, program_id=x["program_id"], query=query)
        ai = None
        ann_purpose = purpose.get(ann_id) if concern else None
        if use_ai and ai_left > 0 and rows:
            ai_left -= 1
            j = await ai_judge.judge(conn, org=org, diag=diagnosis, ann_id=ann_id, title=ann.title,
                                     purpose_text=x["purpose"] or x["summary"], rows=rows, concern=concern,
                                     body=x["body_text"], attachments=x["attachments"], extra_basis=regs,
                                     user_id=user_id)
            rows, ai = j["rows"], j["ai"]
            verdict = verdict_of(rows)
            if j["purpose"] is not None:
                sim = (ann_purpose or {}).get("similarity")
                ann_purpose = {**j["purpose"], "similarity": sim}
        mand = [r for r in rows if r["is_mandatory"]]
        met = sum(r["result"] == "MET" for r in mand)
        q1 = Q1_KO[verdict]
        q1_text = (f"필수요건 {len(mand)}건 모두 충족" if verdict == "ELIGIBLE"
                   else f"필수요건 {len(mand)}건 중 {met}건 충족")
        bonus = [{"description": r["description"], "points": r["bonus_points"]}
                 for r in rows if not r["is_mandatory"] and r["result"] == "MET" and r["bonus_points"]]
        f = fit.evaluate(x["eval_items"], area_scores, ann_purpose, bonus, crit)
        todo = [{"kind": "REQUIREMENT", "text": f"{r['description']}: {r['reason']}",
                 "question": r["question"]} for r in mand if r["result"] != "MET"]
        todo += [{"kind": "FIT", "text": h["text"], "question": None} for h in f["hints"][:2]]
        docs = x["submit_documents"] or []
        results.append({
            "announcement_id": ann_id, "announcement_no": x["announcement_no"], "title": ann.title,
            "agency_name": ann.agency_name, "program_name": x["program_name"],
            "receipt_state": x["receipt_state"], "receipt_start": x["receipt_start"], "receipt_end": x["receipt_end"],
            "verdict": verdict, "q1_label": q1, "q1_text": f"{q1_text}: {q1}",
            "checks": rows, "fit": f,
            "todo": todo,
            "guide": {"support_amount_krw": x["support_amount_krw"],
                      "support_period_months": x["support_period_months"],
                      "company_burden": x["company_burden"],
                      "submit_documents": docs,
                      "text": _guide_text(x, docs)},
            "unsupported": [r["requirement_id"] for r in rows if not r["has_basis"]],
            "ai": ai,
            "regulations": [{"ref": g["ref"], "text": g["text"][:300], "confirmed_at": g["confirmed_at"]}
                            for g in regs[:3]],
            "criteria": {"requirements_confirmed_at": x["requirements_confirmed_at"],
                         "announcement_updated_at": x["ann_updated_at"],
                         "regulations_confirmed_at": min((g["confirmed_at"] for g in regs if g["confirmed_at"]),
                                                         default=None),
                         "unconfirmed_regulations": sorted({g["regulation_title"] for g in regs
                                                            if not g["confirmed_at"]})},
        })
    results.sort(key=lambda r: (ORDER[r["verdict"]], -(r["fit"]["score"] or -1), r["announcement_id"]))
    return {
        "organization_id": org_id, "company_name": org.name, "as_of": date.today().isoformat(),
        "concern": concern, "diagnosis": {"total_score": diagnosis["total_score"],
                                          "state_label": diagnosis["state_label"], "areas": area_scores},
        "summary": {k: sum(r["verdict"] == k for r in results) for k in Q1_KO},
        "results": results,
        "notice": "판정 결과는 상담 참고자료입니다. 최종 자격 판정은 담당자가 확정합니다.",
        "ai_mode": "llm" if use_ai else "rules",
        "fit_rule": {k: crit[k] for k in (*criteria.NUMBERS, "version")},
    }


def verdict_of(rows: list[dict]) -> str:
    mand = [r["result"] for r in rows if r["is_mandatory"]]
    if "UNMET" in mand:
        return "INELIGIBLE"
    if "UNKNOWN" in mand:
        return "NEEDS_INFO"
    return "ELIGIBLE"


def _guide_text(x: dict, docs: list[dict]) -> str:
    parts = []
    if x["company_burden"]:
        parts.append(f"기업부담: {x['company_burden']}")
    if docs:
        parts.append("제출서류: " + ", ".join(d["name"] + ("" if d.get("required", True) else "(해당 시)")
                                            for d in docs))
    return " | ".join(parts)
