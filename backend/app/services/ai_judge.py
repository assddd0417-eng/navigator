"""LLM 자격 판단 (근거 인용) + 계산 검증. 자격 판단 한 번에 LLM 을 한 번 부른다 (검토 공고를 묶어서 보냄).

  입력     공고별 요건 목록(설명·근거 조항)과 근거 자료(공고 조항·본문·첨부·운영규정 조문), 기업정보, 상담 내용
  출력     공고별로 요건별 충족·미충족·확인 필요와 이유·인용문, 사업 목적 부합 수준
  검증     1) 인용문이 근거 자료나 기업정보에 그대로 없으면 그 판단은 버린다 (근거 없는 판단 차단)
           2) 규칙 엔진이 값으로 판정한 요건(업력·규모·등급·이력 등)은 규칙 결과를 쓴다 (계산 검증).
              LLM 과 다르면 차단 목록에 남긴다
           3) 규칙이 '확인 필요'로 둔 수치 요건은 LLM 이 충족이라 해도 확인 필요로 둔다
  LLM 을 못 쓰면 규칙 결과를 그대로 쓴다.
"""
from __future__ import annotations

import re

from psycopg import AsyncConnection

from app.services import ai_gateway
from app.services.eligibility import DISQUALIFY_KO, RESULT_KO, CompanyFacts

TEXT_ONLY = {"OTHER"}          # 규칙 엔진이 값으로 판정하지 못하는 서술형 요건
MAX_BASIS_CHARS = 6000
SIZE_KO = {"SME": "중소기업", "STARTUP": "창업기업", "VENTURE": "벤처기업", "MIDSIZE": "중견기업", "LARGE": "대기업"}
JUDGED_KO = {"RULE": "규칙", "LLM": "근거 인용 판단", "CALC": "계산 검증"}


def _n(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def facts_lines(org: CompanyFacts, diag: dict | None) -> list[str]:
    """LLM 에 보내는 기업정보 (이름·사업자번호 제외)."""
    yn = lambda v: "모름" if v is None else ("해당" if v else "해당 없음")
    out = [f"기업규모: {SIZE_KO.get(org.company_size, org.company_size or '모름')}",
           f"개업일: {org.opened_on or '모름'}", f"소재지: {org.region or '모름'}",
           f"상시 근로자: {org.employee_count if org.employee_count is not None else '모름'}명",
           f"매출: {org.revenue_krw if org.revenue_krw is not None else '모름'}원",
           f"사업자 상태: {org.business_status}", f"방산업체 지정: {'예' if org.is_defense_company else '아니오'}",
           f"국세·지방세 체납: {yn(org.tax_delinquent)}", f"부도·자본잠식: {yn(org.insolvent)}",
           f"국가 R&D 참여제한: {yn(org.rnd_restricted)}", f"부정당제재: {yn(org.procurement_sanctioned)}",
           f"수출 실적: {org.export_krw if org.export_krw is not None else '모름'}원"]
    out.append("인증: " + (", ".join(c.code for c in org.certs) or "없음"))
    if org.support:
        out += [f"지원사업 이력: {s.program_name} ({s.year or '연도 모름'}, {s.result})" for s in org.support]
    else:
        out.append("지원사업 이력: 입력 없음")
    out += [f"R&D 과제: {r.title} ({r.role}, 종료 {r.end_date or '모름'})" for r in org.rnd[:10]]
    if diag:
        out += [f"진단 변수 {v['name']}: {v['display'] or '미확보'}" for v in diag.get("variables", [])]
    return out


def _paragraphs(text: str | None) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n|\n(?=\s*[0-9가-힣○□■①-⑳-])", text or "") if len(p.strip()) >= 8]


def basis_passages(reqs: list[dict], body: str | None, attachments: list[str], extra: list[dict]) -> list[dict]:
    """근거 자료: 요건의 공고 조항 + 요건 낱말이 많이 겹치는 본문·첨부 문단 + 운영규정 조문(extra)."""
    out: list[dict] = []
    for r in reqs:
        if r.get("source_quote"):
            out.append({"source": "공고 조항", "text": r["source_quote"]})
    words = {w for r in reqs for w in re.findall(r"[가-힣A-Za-z]{2,}", r["description"] or "")}
    paras = [("공고 본문", p) for p in _paragraphs(body)] + [("첨부", p) for t in attachments for p in _paragraphs(t)]
    scored = sorted(paras, key=lambda x: -sum(w in x[1] for w in words))
    used = sum(len(p["text"]) for p in out)
    for src, p in scored:
        if used > MAX_BASIS_CHARS or not any(w in p for w in words):
            break
        out.append({"source": src, "text": p[:800]})
        used += len(p[:800])
    for e in extra:
        out.append({"source": e.get("source", "운영규정"), "text": e["text"], "ref": e.get("ref")})
    return out


def _quote_ok(quote: str | None, basis: list[dict], facts: list[str]) -> bool:
    q = _n(quote)
    if len(q) < 4:
        return False
    return any(q in _n(b["text"]) for b in basis) or any(q in _n(f) for f in facts)


def merge(rows: list[dict], out: dict | None, basis: list[dict], facts: list[str]) -> tuple[list[dict], list[dict]]:
    """규칙 결과(rows)에 LLM 판단을 합친다. 돌려주는 것: 새 rows, 차단 목록."""
    blocked: list[dict] = []
    llm = {}
    for x in (out or {}).get("requirements", []) or []:
        try:
            llm[int(x["requirement_id"])] = x
        except (KeyError, TypeError, ValueError):
            continue
    new = []
    for r in rows:
        r = {**r, "judged_by": "RULE", "judged_label": JUDGED_KO["RULE"], "ai_reason": None, "ai_quote": None}
        x = llm.get(r["requirement_id"])
        if x is None:
            new.append(r)
            continue
        res = x.get("result") if x.get("result") in RESULT_KO else "UNKNOWN"
        if res != "UNKNOWN" and not _quote_ok(x.get("quote"), basis, facts):
            blocked.append({"requirement_id": r["requirement_id"], "reason": "근거 인용 실패",
                            "llm_result": res, "quote": (x.get("quote") or "")[:200]})
            new.append(r)
            continue
        if r["req_type_code"] in TEXT_ONLY:
            r["ai_reason"], r["ai_quote"] = x.get("reason"), x.get("quote")
            r.update(result=res, result_label=RESULT_KO[res], reason=x.get("reason") or r["reason"],
                     question=x.get("question") or (r["question"] if res == "UNKNOWN" else None),
                     judged_by="LLM", judged_label=JUDGED_KO["LLM"], has_basis=r["has_basis"] or bool(x.get("quote")))
        elif r["result"] in ("MET", "UNMET"):
            if res != r["result"]:
                blocked.append({"requirement_id": r["requirement_id"], "reason": "계산 검증 불일치",
                                "llm_result": res, "rule_result": r["result"]})
            else:
                r["ai_reason"], r["ai_quote"] = x.get("reason"), x.get("quote")   # 규칙과 같은 판단만 근거로 보여 줌
            r.update(judged_by="CALC", judged_label=JUDGED_KO["CALC"])
        elif res != "UNKNOWN":
            blocked.append({"requirement_id": r["requirement_id"], "reason": "수치 요건 값 확인 안 됨",
                            "llm_result": res})
        new.append(r)
    return new, blocked


def purpose_from(out: dict | None) -> dict | None:
    p = (out or {}).get("purpose")
    if not isinstance(p, dict) or p.get("level") not in ("FULL", "PARTIAL", "LOW"):
        return None
    return {"level": p["level"], "label": {"FULL": "높음", "PARTIAL": "보통", "LOW": "낮음"}[p["level"]],
            "similarity": None, "reason": (p.get("reason") or "")[:300], "source": "LLM"}


def _by_announcement(out: dict | None, ids: list[int]) -> dict[int, dict]:
    """응답을 공고별로 나눈다. 공고 하나만 보냈을 때는 예전 형식({"requirements", "purpose"})도 받는다."""
    got: dict[int, dict] = {}
    for a in (out or {}).get("announcements", []) or []:
        try:
            got[int(a["announcement_id"])] = a
        except (KeyError, TypeError, ValueError):
            continue
    if not got and len(ids) == 1 and isinstance((out or {}).get("requirements"), list):
        got[ids[0]] = out
    return got


async def judge_many(conn: AsyncConnection, *, org: CompanyFacts, diag: dict | None, items: list[dict],
                     concern: str | None, user_id: int | None) -> dict[int, dict]:
    """검토 공고를 묶어 LLM 을 한 번 부른다.

    items: [{ann_id, title, purpose_text, rows, body, attachments, extra_basis}]
    결과: {ann_id: {rows, purpose, ai {status, model, log_id, blocked, error, prompt_version}}}
    """
    if not items:
        return {}
    facts = facts_lines(org, diag)
    concern = concern.strip() if concern and concern.strip() else None
    bases = {it["ann_id"]: basis_passages(it["rows"], it["body"], it["attachments"], it["extra_basis"])
             for it in items}
    payload = {
        "announcements": [{
            "announcement_id": it["ann_id"], "title": it["title"], "purpose": it["purpose_text"],
            "requirements": [{"requirement_id": r["requirement_id"], "type": r["req_type_name"],
                              "description": r["description"], "mandatory": r["is_mandatory"],
                              "clause": r["source_quote"]} for r in it["rows"]],
            "basis": [{"source": b["source"], "text": b["text"]} for b in bases[it["ann_id"]]],
        } for it in items],
        "company": facts,
        "concern": concern,
    }
    ids = [it["ann_id"] for it in items]
    refs = {"announcement_ids": ids,
            "requirement_ids": [r["requirement_id"] for it in items for r in it["rows"]],
            "mandatory": sum(r["is_mandatory"] for it in items for r in it["rows"]),
            "basis": [{"announcement_id": it["ann_id"], "source": b["source"], "ref": b.get("ref"),
                       "chars": len(b["text"])} for it in items for b in bases[it["ann_id"]]],
            "concern": bool(concern)}
    res = await ai_gateway.call(conn, purpose="ELIGIBILITY_JUDGE", payload=payload, refs=refs,
                                org_id=org.organization_id, ann_id=ids[0] if len(ids) == 1 else None,
                                user_id=user_id)
    rule_rows = lambda rows: [{**r, "judged_by": "RULE", "judged_label": JUDGED_KO["RULE"], "ai_reason": None,
                               "ai_quote": None} for r in rows]
    if res.output is None:
        info = {"status": res.status, "model": res.model, "log_id": res.log_id, "blocked": [],
                "error": res.error, "prompt_version": res.prompt_version}
        return {it["ann_id"]: {"rows": rule_rows(it["rows"]), "purpose": None, "ai": info} for it in items}
    got = _by_announcement(res.output, ids)
    out, all_blocked = {}, []
    for it in items:
        a = got.get(it["ann_id"])
        if a is None:
            new, blocked = rule_rows(it["rows"]), [{"announcement_id": it["ann_id"], "reason": "응답에 공고 없음"}]
        else:
            new, blocked = merge(it["rows"], a, bases[it["ann_id"]], facts)
            blocked = [{"announcement_id": it["ann_id"], **b} for b in blocked]
        all_blocked += blocked
        out[it["ann_id"]] = {
            "rows": new, "purpose": purpose_from(a) if concern and a is not None else None,
            "ai": {"status": "PARTIAL" if blocked and res.status == "OK" else res.status, "model": res.model,
                   "log_id": res.log_id, "blocked": blocked, "error": None, "prompt_version": res.prompt_version}}
    await ai_gateway.mark(conn, res.log_id, all_blocked)
    return out


async def judge(conn: AsyncConnection, *, org: CompanyFacts, diag: dict | None, ann_id: int, title: str,
                purpose_text: str | None, rows: list[dict], concern: str | None, body: str | None,
                attachments: list[str], extra_basis: list[dict], user_id: int | None) -> dict:
    """공고 하나만 판단할 때."""
    out = await judge_many(conn, org=org, diag=diag, concern=concern, user_id=user_id, items=[{
        "ann_id": ann_id, "title": title, "purpose_text": purpose_text, "rows": rows, "body": body,
        "attachments": attachments, "extra_basis": extra_basis}])
    return out[ann_id]


__all__ = ["judge", "judge_many", "merge", "basis_passages", "facts_lines", "DISQUALIFY_KO"]
