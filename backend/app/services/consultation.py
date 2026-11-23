"""상담 요청·상담 이력·상담결과서.

  상담 실행   D-STATE 진단(이력 저장) + 업무 B·C 면 자격요건 검토 + 업무 C 면 성장경로. 결과 스냅샷과
              상담결과서 초안을 consultation 에 저장한다.
  결과서      템플릿 문장으로 초안을 만들고, AI 판단을 켜면 LLM 이 문장만 다듬는다 (새 숫자·약속 표현이 생기면
              그 항목은 템플릿 문장을 쓴다). 초안(draft)은 고치지 않고 남긴다. 담당자는 report 를 고친다.
  판정 수정   담당자가 공고별 신청 가능 여부를 바꾸면 사유와 함께 overrides 에 남긴다.
  확정        확정한 상담만 기업 화면에 보인다. 확정 후에는 고치지 않는다 (새로 상담).
  이력 점검   초안과 다르게 고친 결과서 항목, 판정 수정 사례를 모아 기준 보정에 쓴다.
"""
from __future__ import annotations

import re

from fastapi.encoders import jsonable_encoder
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.services import ai_gateway, consult_evidence, dstate, eligibility_review, mailer, route

TASK_KO = {"A": "D-STATE 진단", "B": "자격요건 검토", "C": "종합 성장경로"}
STATUS_KO = {"DRAFT": "검토 중", "CONFIRMED": "확정"}
REQUEST_KO = {"REQUESTED": "요청", "IN_PROGRESS": "상담 중", "DONE": "완료", "CANCELED": "취소"}
VERDICTS = ("ELIGIBLE", "NEEDS_INFO", "INELIGIBLE")
NOTICE = ("본 결과서는 상담 참고자료이며 지원사업 선정·지원을 보장하지 않습니다. "
          "최종 신청 자격과 선정 여부는 각 사업 공고와 소관기관 심사에 따릅니다.")
SECTIONS = [("overview", "기업 개요"), ("diagnosis", "성장준비도 진단"), ("eligibility", "지원사업 검토 결과"),
            ("route", "추천 성장경로"), ("request", "보완 요청 사항"), ("opinion", "담당자 의견"), ("notice", "유의사항")]
MAX_ANN_LINES = 5
POLISH_KEYS = ("overview", "diagnosis", "eligibility", "route", "request")
PROMISE = re.compile(r"선정\s*(확정|보장|됩니다|될 것)|지원\s*(보장|확정)|반드시\s*선정")
COMPANY = "[기업]"


class ConsultError(ValueError):
    pass


# ---------- 결과서 ----------

def _diag_snapshot(d: dict) -> dict:
    keep = ("rule_version", "as_of", "total_score", "state_type", "state_label", "weakest_area", "weakest_label",
            "areas", "strengths", "tasks", "missing", "summary", "company_name", "diagnosis_id", "previous")
    out = {k: d.get(k) for k in keep}
    out["missing_labels"] = [v["name"] for v in d.get("variables", []) if v["missing"]]
    out["areas"] = [{"code": a["code"], "label": a["label"], "score": a["score"]} for a in d["areas"]]
    return out


def build_report(diag: dict, elig: dict | None, rt: dict | None, concern: str | None) -> list[dict]:
    text: dict[str, str] = {}
    text["overview"] = (f"{diag['company_name']} | 상태유형 {diag['state_label']} | 종합 준비도 {diag['total_score']}점"
                        f"\n상담 내용: {concern.strip() if concern and concern.strip() else '없음'}")
    lines = [diag["summary"]]
    lines += [f"- 강점: {s['label']} {s['score']}점, {s['text']}" for s in diag["strengths"][:2]]
    lines += [f"- 보완: {t['label']} {t['score']}점, {t['text']}" for t in diag["tasks"][:2]]
    text["diagnosis"] = "\n".join(lines)

    questions: list[str] = []
    if elig is not None:
        text["eligibility"] = eligibility_text(elig)
        for r in [r for r in elig["results"] if r["verdict"] != "INELIGIBLE"][:MAX_ANN_LINES]:
            questions += [t["question"] for t in r["todo"] if t.get("question")]
    else:
        text["eligibility"] = "이번 상담에서는 검토하지 않음."
    if rt is not None:
        lines = [rt["summary"]]
        for st in rt["steps"]:
            progs = ", ".join(f"{p['name']}({p['readiness_label']})" for p in st["programs"]) or "추천 사업 없음"
            lines.append(f"- {st['horizon']} {st['stage_label']}: {progs}. 준비과제: {', '.join(st['tasks']) or '없음'}")
        text["route"] = "\n".join(lines)
    else:
        text["route"] = "이번 상담에서는 검토하지 않음."
    req = [f"- 진단 정보 확인: {', '.join(diag['missing_labels'])}"] if diag["missing_labels"] else []
    req += [f"- {q}" for q in dict.fromkeys(questions)][:5]
    text["request"] = "\n".join(req) or "없음"
    text["opinion"] = ""
    text["notice"] = NOTICE
    return [{"key": k, "title": t, "text": text[k]} for k, t in SECTIONS]


def eligibility_text(elig: dict, overrides: list[dict] | None = None) -> str:
    """'지원사업 검토 결과' 항목. 담당자가 바꾼 판정이 있으면 바꾼 판정으로 센다."""
    changed = {o["announcement_id"]: o["verdict"] for o in overrides or []}
    res = [{**r, "final": changed.get(r["announcement_id"], r["verdict"])} for r in elig["results"]]
    count = {v: sum(1 for r in res if r["final"] == v) for v in VERDICTS}
    lines = [f"검토 공고 {len(res)}건: 신청 가능 {count['ELIGIBLE']}건, 확인 필요 {count['NEEDS_INFO']}건, "
             f"신청 불가 {count['INELIGIBLE']}건"]
    for r in [r for r in res if r["final"] != "INELIGIBLE"][:MAX_ANN_LINES]:
        if r["final"] != r["verdict"]:
            lines.append(f"- {r['title']}: {eligibility_review.Q1_KO[r['final']]} (담당자 확인), "
                         f"적합도 {r['fit']['grade_label']}")
            continue
        fix = "; ".join(t["text"] for t in r["todo"][:2])
        lines.append(f"- {r['title']}: {r['q1_label']}, 적합도 {r['fit']['grade_label']}"
                     + (f". 보완: {fix}" if fix else ""))
    return "\n".join(lines)


def _numbers(t: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)*", t or ""))


def check_polished(draft: list[dict], out: dict | None) -> tuple[dict[str, str], list[dict]]:
    """LLM 이 다듬은 문장 중 쓸 것만 고른다. 돌려주는 것: {key: 문장}, 차단 목록."""
    src = {s["key"]: s["text"] for s in draft}
    got, blocked = {}, []
    for x in (out or {}).get("sections", []) or []:
        k, t = x.get("key"), x.get("text")
        if k not in POLISH_KEYS or not isinstance(t, str) or not src.get(k):
            continue
        t = t.strip()
        if not t:
            blocked.append({"section": k, "reason": "빈 문장"})
        elif extra := sorted(_numbers(t) - _numbers(src[k])):
            blocked.append({"section": k, "reason": "초안에 없는 숫자", "numbers": extra[:5]})
        elif PROMISE.search(t):
            blocked.append({"section": k, "reason": "선정·지원 약속 표현"})
        else:
            got[k] = t
    return got, blocked


async def polish_report(conn: AsyncConnection, report: list[dict], *, org_id: int, company_name: str | None,
                        user_id: int | None) -> tuple[list[dict], dict]:
    """결과서 초안 문장 다듬기. 기업 이름은 [기업]으로 바꿔 보낸다. LLM 을 못 쓰면 템플릿 문장 그대로."""
    marked = [{**s, "drafted_by": "TEMPLATE"} for s in report]
    if ai_gateway.mode() != "llm":
        return marked, {"status": "FALLBACK", "log_id": None, "blocked": []}
    hide = (lambda t: t.replace(company_name, COMPANY)) if company_name else (lambda t: t)
    send = [{"key": s["key"], "title": s["title"], "text": hide(s["text"])}
            for s in report if s["key"] in POLISH_KEYS and s["text"]]
    res = await ai_gateway.call(conn, purpose="REPORT_DRAFT", payload={"sections": send},
                                refs={"sections": [s["key"] for s in send]}, org_id=org_id, user_id=user_id)
    if res.output is None:
        return marked, {"status": res.status, "log_id": res.log_id, "blocked": [], "error": res.error}
    got, blocked = check_polished(send, res.output)
    await ai_gateway.mark(conn, res.log_id, blocked)
    show = (lambda t: t.replace(COMPANY, company_name)) if company_name else (lambda t: t)
    out = [{**s, "text": show(got[s["key"]]), "drafted_by": "LLM"} if s["key"] in got else s for s in marked]
    return out, {"status": "PARTIAL" if blocked and res.status == "OK" else res.status, "log_id": res.log_id,
                 "blocked": blocked, "model": res.model, "prompt_version": res.prompt_version}


# ---------- 상담 실행 ----------

async def run(conn: AsyncConnection, org_id: int, *, task: str, concern: str | None, request_id: int | None,
              user_id: int, evidence_ids: list[int] | None = None) -> dict:
    if request_id is not None:
        req = await (await conn.execute(
            "SELECT organization_id, status, concern FROM ax.consult_request WHERE id = %s",
            (request_id,))).fetchone()
        if req is None or req["organization_id"] != org_id:
            raise ConsultError("이 기업의 상담 요청이 아님")
        if not concern:
            concern = req["concern"]
    diag = await dstate.run(conn, org_id, save=True, user_id=user_id, reuse_same=True)
    elig = rt = None
    if task in ("B", "C"):
        elig = await eligibility_review.review(conn, org_id, concern=concern, diagnosis=diag, user_id=user_id)
    if task == "C":
        rt = await route.build(conn, org_id, concern=concern, diagnosis=diag, review=elig, user_id=user_id)
    snap = _diag_snapshot(diag)
    report, _ = await polish_report(conn, build_report(snap, elig, rt, concern), org_id=org_id,
                                    company_name=snap.get("company_name"), user_id=user_id)
    row = await (await conn.execute(
        """INSERT INTO ax.consultation (organization_id, request_id, task, concern, diagnosis_id, diagnosis,
                                        eligibility, route, draft, report, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (org_id, request_id, task, concern, diag["diagnosis_id"], Jsonb(jsonable_encoder(snap)),
         Jsonb(jsonable_encoder(elig)) if elig is not None else None,
         Jsonb(jsonable_encoder(rt)) if rt is not None else None,
         Jsonb(report), Jsonb(report), user_id))).fetchone()
    if request_id is not None:
        await conn.execute(
            """UPDATE ax.consult_request SET status = 'IN_PROGRESS', handled_by = %s, updated_at = now()
                WHERE id = %s AND status = 'REQUESTED'""", (user_id, request_id))
    await consult_evidence.link(conn, org_id, row["id"], evidence_ids or [])
    return await get(conn, row["id"])


# ---------- 조회 ----------

def _verdicts(c: dict) -> dict[int, str]:
    """공고별 최종 판정 (담당자 수정 반영)."""
    out = {r["announcement_id"]: r["verdict"] for r in (c["eligibility"] or {}).get("results", [])}
    for o in c["overrides"]:
        out[o["announcement_id"]] = o["verdict"]
    return out


def compare(prev: dict | None, cur: dict) -> dict | None:
    """직전 상담 대비 변화 (재상담)."""
    if prev is None:
        return None
    ps = {a["code"]: a["score"] for a in prev["diagnosis"]["areas"]}
    areas = [{"code": a["code"], "label": a["label"], "before": ps.get(a["code"]), "after": a["score"],
              "delta": a["score"] - ps[a["code"]] if a["code"] in ps else None}
             for a in cur["diagnosis"]["areas"]]
    pv, cv = _verdicts(prev), _verdicts(cur)
    titles = {r["announcement_id"]: r["title"] for c in (prev, cur)
              for r in (c["eligibility"] or {}).get("results", [])}
    changed = [{"announcement_id": a, "title": titles.get(a), "before": eligibility_review.Q1_KO[pv[a]],
                "after": eligibility_review.Q1_KO[cv[a]]}
               for a in cv if a in pv and pv[a] != cv[a]]
    return {"consultation_id": prev["id"], "created_at": prev["created_at"],
            "total_before": prev["diagnosis"]["total_score"], "total_after": cur["diagnosis"]["total_score"],
            "state_before": prev["diagnosis"]["state_label"], "state_after": cur["diagnosis"]["state_label"],
            "areas": areas, "verdict_changes": changed}


SELECT = """SELECT c.*, u.name AS created_by_name, cu.name AS confirmed_by_name, o.name AS company_name,
                   r.concern AS request_concern, r.interest AS request_interest
              FROM ax.consultation c JOIN ax.organization o ON o.id = c.organization_id
              LEFT JOIN ax.app_user u ON u.id = c.created_by
              LEFT JOIN ax.app_user cu ON cu.id = c.confirmed_by
              LEFT JOIN ax.consult_request r ON r.id = c.request_id"""


def _out(c: dict) -> dict:
    for k in ("created_at", "updated_at", "confirmed_at", "shared_at", "notified_at"):
        c[k] = c[k].isoformat() if c.get(k) else None
    c["task_label"] = TASK_KO[c["task"]]
    c["status_label"] = STATUS_KO[c["status"]]
    c["edited_sections"] = [s["key"] for s, d in zip(c["report"], c["draft"]) if s["text"] != d["text"]]
    return c


async def _prev(conn: AsyncConnection, c: dict) -> dict | None:
    row = await (await conn.execute(
        SELECT + " WHERE c.organization_id = %s AND c.id < %s ORDER BY c.id DESC LIMIT 1",
        (c["organization_id"], c["id"]))).fetchone()
    return _out(row) if row else None


async def get(conn: AsyncConnection, cid: int) -> dict | None:
    row = await (await conn.execute(SELECT + " WHERE c.id = %s", (cid,))).fetchone()
    if row is None:
        return None
    c = _out(row)
    c["compare"] = compare(await _prev(conn, c), c)
    c["evidence"] = await consult_evidence.list_for(conn, c["organization_id"], consultation_id=cid)
    return c


async def history(conn: AsyncConnection, org_id: int) -> list[dict]:
    rows = await (await conn.execute(
        SELECT + " WHERE c.organization_id = %s ORDER BY c.id DESC", (org_id,))).fetchall()
    out = []
    for r in rows:
        c = _out(r)
        v = list(_verdicts(c).values())
        out.append({"id": c["id"], "task": c["task"], "task_label": c["task_label"], "status": c["status"],
                    "status_label": c["status_label"], "concern": c["concern"],
                    "total_score": c["diagnosis"]["total_score"], "state_label": c["diagnosis"]["state_label"],
                    "eligible_count": v.count("ELIGIBLE") if c["eligibility"] else None,
                    "override_count": len(c["overrides"]), "edited_sections": c["edited_sections"],
                    "feedback": c["feedback"], "created_at": c["created_at"], "created_by_name": c["created_by_name"],
                    "confirmed_at": c["confirmed_at"], "confirmed_by_name": c["confirmed_by_name"]})
    return out


# ---------- 담당자 수정·확정 ----------

async def update(conn: AsyncConnection, cid: int, *, report: dict[str, str] | None,
                 overrides: list[dict] | None, feedback: str | None) -> dict:
    c = await get(conn, cid)
    if c is None:
        raise LookupError(cid)
    if c["status"] != "DRAFT":
        raise ConsultError("확정한 상담은 고칠 수 없음. 새로 상담하세요")
    new_report = c["report"]
    if report is not None:
        keys = {s["key"] for s in new_report}
        if bad := [k for k in report if k not in keys]:
            raise ConsultError(f"없는 항목: {bad}")
        new_report = [{**s, "text": report.get(s["key"], s["text"])} for s in new_report]
    new_over = c["overrides"]
    if overrides is not None:
        results = {r["announcement_id"]: r for r in (c["eligibility"] or {}).get("results", [])}
        new_over = []
        for o in overrides:
            r = results.get(o["announcement_id"])
            if r is None:
                raise ConsultError(f"이번 상담에서 검토하지 않은 공고: {o['announcement_id']}")
            if o["verdict"] == r["verdict"]:
                continue
            new_over.append({"announcement_id": r["announcement_id"], "title": r["title"],
                             "from": r["verdict"], "verdict": o["verdict"], "reason": o["reason"]})
    new_draft = c["draft"]
    if c["eligibility"] and new_over != c["overrides"]:
        # 담당자가 손대지 않은 '지원사업 검토 결과'는 바꾼 판정에 맞춰 다시 쓴다 (기업 안내와 판정이 어긋나지 않게)
        drafted = {d["key"]: d["text"] for d in c["draft"]}
        cur = {s["key"]: s["text"] for s in new_report}
        if cur.get("eligibility") == drafted.get("eligibility"):
            text = eligibility_text(c["eligibility"], new_over)
            fix = lambda secs: [{**s, "text": text, "drafted_by": "TEMPLATE"} if s["key"] == "eligibility" else s
                                for s in secs]
            new_report, new_draft = fix(new_report), fix(c["draft"])
    await conn.execute(
        """UPDATE ax.consultation SET report = %s, draft = %s, overrides = %s, feedback = %s, updated_at = now()
            WHERE id = %s""",
        (Jsonb(new_report), Jsonb(new_draft), Jsonb(new_over), feedback if feedback is not None else c["feedback"],
         cid))
    return await get(conn, cid)


def _mail_body(c: dict) -> str:
    return (f"{c['company_name']} 담당자님께\n\n"
            f"{c['created_at'][:10]} 상담 결과가 확정되었습니다.\n"
            "기업 정보 관리 화면의 '상담' 메뉴에서 상담결과서와 추천 지원사업을 볼 수 있습니다. "
            "관리 링크가 만료되었으면 사업자번호로 다시 요청하세요.\n\n" + NOTICE)


async def confirm(conn: AsyncConnection, cid: int, user_id: int, notify: bool) -> dict:
    c = await get(conn, cid)
    if c is None:
        raise LookupError(cid)
    if c["status"] != "DRAFT":
        raise ConsultError("이미 확정한 상담")
    await conn.execute(
        """UPDATE ax.consultation SET status = 'CONFIRMED', confirmed_by = %s, confirmed_at = now(),
                  shared_at = now(), updated_at = now() WHERE id = %s""", (user_id, cid))
    if c["request_id"]:
        await conn.execute("UPDATE ax.consult_request SET status = 'DONE', updated_at = now() WHERE id = %s",
                           (c["request_id"],))
    out = await get(conn, cid)
    out["notify"] = None
    if notify:
        email = (await (await conn.execute(
            "SELECT registered_email FROM ax.company_profile WHERE organization_id = %s",
            (c["organization_id"],))).fetchone() or {}).get("registered_email")
        if not email:
            out["notify"] = {"sent": False, "reason": "등록된 이메일 없음"}
        else:
            try:
                await mailer.send_async(email, "[Navigator] 상담 결과 안내", _mail_body(out))
                await conn.execute("UPDATE ax.consultation SET notified_at = now() WHERE id = %s", (cid,))
                out["notify"] = {"sent": True, "to": mailer.mask_email(email)}
            except mailer.MailError as e:
                out["notify"] = {"sent": False, "reason": str(e)}
    return out


# ---------- 이력 점검 ----------

async def review_log(conn: AsyncConnection, limit: int = 100,
                     access: tuple[str, dict] = ("TRUE", {})) -> dict:
    """담당자가 초안과 다르게 고치거나 판정을 바꾼 상담. 기준 보정 점검용. access = 열람 권한 조건."""
    cond, params = access
    rows = await (await conn.execute(
        SELECT + f""" WHERE ({cond}) AND (c.overrides <> '[]'::jsonb OR c.report <> c.draft OR c.feedback IS NOT NULL)
                    ORDER BY c.id DESC LIMIT %(n)s""", {**params, "n": limit})).fetchall()
    titles = dict(SECTIONS)
    items, by_type = [], {"overrides": 0, "edits": 0, "feedback": 0}
    for r in rows:
        c = _out(r)
        by_type["overrides"] += len(c["overrides"])
        by_type["edits"] += len(c["edited_sections"])
        by_type["feedback"] += 1 if c["feedback"] else 0
        items.append({
            "consultation_id": c["id"], "company_name": c["company_name"], "task_label": c["task_label"],
            "status_label": c["status_label"], "created_at": c["created_at"], "created_by_name": c["created_by_name"],
            "overrides": [{**o, "from_label": eligibility_review.Q1_KO[o["from"]],
                           "verdict_label": eligibility_review.Q1_KO[o["verdict"]]} for o in c["overrides"]],
            "edited_sections": [titles[k] for k in c["edited_sections"]],
            "feedback": c["feedback"]})
    total = (await (await conn.execute(
        f"SELECT count(*) AS n, count(*) FILTER (WHERE status = 'CONFIRMED') AS confirmed FROM ax.consultation c WHERE {cond}",
        params)).fetchone())
    return {"total": total["n"], "confirmed": total["confirmed"], "counts": by_type, "items": items}


# ---------- 상담 요청 ----------

async def create_request(conn: AsyncConnection, org_id: int, data: dict, origin: str,
                         user_id: int | None = None) -> dict:
    row = await (await conn.execute(
        """INSERT INTO ax.consult_request (organization_id, concern, interest, contact_name, contact_phone, origin,
                                           handled_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (org_id, data["concern"], data.get("interest"), data.get("contact_name"), data.get("contact_phone"),
         origin, user_id))).fetchone()
    return (await list_requests(conn, request_id=row["id"]))[0]


async def list_requests(conn: AsyncConnection, *, status: str | None = None, org_id: int | None = None,
                        request_id: int | None = None) -> list[dict]:
    rows = await (await conn.execute(
        """SELECT r.*, o.name AS company_name, u.name AS handled_by_name,
                  (SELECT max(c.id) FROM ax.consultation c WHERE c.request_id = r.id) AS consultation_id
             FROM ax.consult_request r JOIN ax.organization o ON o.id = r.organization_id
             LEFT JOIN ax.app_user u ON u.id = r.handled_by
            WHERE (%(s)s::text IS NULL OR r.status = %(s)s) AND (%(o)s::bigint IS NULL OR r.organization_id = %(o)s)
              AND (%(i)s::bigint IS NULL OR r.id = %(i)s)
            ORDER BY (r.status = 'REQUESTED') DESC, r.created_at DESC LIMIT 200""",
        {"s": status, "o": org_id, "i": request_id})).fetchall()
    for r in rows:
        r["status_label"] = REQUEST_KO[r["status"]]
        r["created_at"] = r["created_at"].isoformat()
        r["updated_at"] = r["updated_at"].isoformat()
    return rows


async def set_request_status(conn: AsyncConnection, rid: int, status: str, user_id: int) -> dict:
    row = await (await conn.execute(
        """UPDATE ax.consult_request SET status = %s, handled_by = %s, updated_at = now() WHERE id = %s
           RETURNING id""", (status, user_id, rid))).fetchone()
    if row is None:
        raise LookupError(rid)
    return (await list_requests(conn, request_id=rid))[0]


# ---------- 기업 화면 ----------

_N = r"\d+(?:\.\d+)?\s*점"
_SCORE = [
    (re.compile(r"\s*\|\s*종합 준비도\s*" + _N), ""),                  # 개요 '| 종합 준비도 62점'
    (re.compile(r"(준비도는)\s*" + _N + r"으로"), r"\1"),                 # 요약 '종합 준비도는 71점으로 ~ 단계'
    (re.compile(r"\s*\(\s*" + _N + r"\s*\)"), ""),                       # '기술성(72점)'
    (re.compile(r"\s*·\s*\d+(?:\.\d+)?\s*%"), ""),                       # '보통 · 41%'
    (re.compile(r"\s*" + _N + r"(?:으로|이고|이며|이다|임|입니다)?"), ""),   # 나머지 '72점', 담당자가 고쳐 쓴 문장
]


def strip_scores(text: str) -> str:
    """기업에게 보이는 판본에서 점수를 뺀다. 라벨·문장은 담당자가 확정한 그대로 둔다."""
    text = text or ""
    for pat, rep in _SCORE:
        text = pat.sub(rep, text)
    return text


async def company_view(conn: AsyncConnection, org_id: int) -> dict:
    """확정한 상담만. 점수는 빼고 라벨로 보여 준다 (결과서 본문은 담당자가 확정한 그대로)."""
    rows = await (await conn.execute(
        SELECT + " WHERE c.organization_id = %s AND c.status = 'CONFIRMED' ORDER BY c.id DESC LIMIT 10",
        (org_id,))).fetchall()
    out = []
    for r in rows:
        c = _out(r)
        v = _verdicts(c)
        anns = [{"announcement_id": x["announcement_id"], "title": x["title"], "agency_name": x["agency_name"],
                 "receipt_end": x["receipt_end"], "q1_label": eligibility_review.Q1_KO[v[x["announcement_id"]]],
                 "fit_grade": x["fit"]["grade"], "todo": [] if v[x["announcement_id"]] == "ELIGIBLE" and x["verdict"] != "ELIGIBLE"  # 담당자가 신청 가능으로 확인
                 else [t["text"] for t in x["todo"] if t["kind"] != "FIT"][:3]}
                for x in (c["eligibility"] or {}).get("results", [])
                if v[x["announcement_id"]] != "INELIGIBLE"]
        steps = [{"horizon": s["horizon"], "stage_label": s["stage_label"], "goal": s["goal"],
                  "programs": [{"name": p["name"], "readiness_label": p["readiness_label"]} for p in s["programs"]],
                  "tasks": s["tasks"]} for s in (c["route"] or {}).get("steps", [])]
        out.append({"id": c["id"], "task_label": c["task_label"], "confirmed_at": c["confirmed_at"],
                    "concern": c["concern"], "state_label": c["diagnosis"]["state_label"],
                    "report": [{**s, "text": strip_scores(s["text"])} for s in c["report"] if s["text"]], "announcements": anns, "steps": steps})
    requests = await list_requests(conn, org_id=org_id)
    return {"consultations": out,
            "requests": [{k: r[k] for k in ("id", "concern", "interest", "status", "status_label", "created_at")}
                         for r in requests]}
