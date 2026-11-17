"""담당자 참여 권유. 공고별 마지막 매칭 결과에서 적합·확인 필요이고 권유 메일에 동의한 기업에만 보낸다.

같은 공고·기업에는 한 번만 보낸다. 메일마다 수신 거부 링크를 넣고, 누르면 동의가 풀린다.
"""
from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass

from psycopg import AsyncConnection

from app.config import get_settings
from app.db import transaction
from app.errors import Conflict, NotFound
from app.services import mailer
from app.services.access_link import hash_token
from app.services.bizno import format_bizno
from app.services.eligibility import COMPANY_VERDICT_KO, VERDICT_KO

log = logging.getLogger("app.navigator_outreach")

SKIP_KO = {
    "NOT_IN_RESULT": "판정 결과에 없음",
    "INELIGIBLE": "부적격",
    "NO_CONSENT": "권유 메일 동의 안 함",
    "NO_EMAIL": "등록 이메일 없음",
    "ALREADY_SENT": "이미 보냄",
}


def _base() -> str:
    return get_settings().navigator_public_base_url.rstrip("/")


def optout_url(token: str) -> str:
    return f"{_base()}/navigator/outreach/optout#t={token}"


async def set_consent(conn: AsyncConnection, org_id: int, consent: bool) -> dict:
    row = await (await conn.execute(
        """UPDATE ax.company_profile
              SET outreach_consent_at = CASE WHEN %s THEN coalesce(outreach_consent_at, now()) END
            WHERE organization_id = %s RETURNING outreach_consent_at""", (consent, org_id))).fetchone()
    if row is None:
        raise NotFound("기업 프로필", org_id)
    return {"outreach_consent": row["outreach_consent_at"] is not None,
            "outreach_consent_at": row["outreach_consent_at"]}


async def _latest_run(conn: AsyncConnection, ann_id: int) -> int | None:
    row = await (await conn.execute(
        """SELECT id FROM ax.company_match_run WHERE announcement_id = %s
              AND direction = 'ANNOUNCEMENT_TO_COMPANY' AND requested_via <> 'SYSTEM'
            ORDER BY created_at DESC, id DESC LIMIT 1""", (ann_id,))).fetchone()
    return row["id"] if row else None


async def candidates(conn: AsyncConnection, ann_id: int) -> dict:
    """마지막 매칭 결과의 적합·확인 필요 기업과 권유 가능 여부, 보낸 기록."""
    ann = await (await conn.execute(
        "SELECT id, title, status, receipt_state FROM ax.v_announcement WHERE id = %s", (ann_id,))).fetchone()
    if ann is None:
        raise NotFound("공고", ann_id)
    run_id = await _latest_run(conn, ann_id)
    rows = [] if run_id is None else await (await conn.execute(
        """SELECT cr.id AS recommendation_id, cr.organization_id, o.name AS company_name, cr.verdict,
                  cr.total_score::float AS total_score, cr.rank,
                  cp.outreach_consent_at IS NOT NULL AS consent, cp.registered_email IS NOT NULL AS has_email,
                  m.status AS sent_status, m.sent_at, m.error AS sent_error
             FROM ax.company_recommendation cr
             JOIN ax.organization o ON o.id = cr.organization_id
             JOIN ax.company_profile cp ON cp.organization_id = cr.organization_id
             LEFT JOIN ax.outreach_message m ON m.announcement_id = %s AND m.organization_id = cr.organization_id
            WHERE cr.match_run_id = %s AND cr.verdict IN ('ELIGIBLE', 'NEEDS_INFO')
            ORDER BY cr.rank""", (ann_id, run_id))).fetchall()
    for r in rows:
        r["verdict_label"] = VERDICT_KO[r["verdict"]]
        r["sendable"] = r["consent"] and r["has_email"] and r["sent_status"] not in ("PENDING", "SENT")
    return {"announcement_id": ann_id, "match_run_id": run_id,
            "open": ann["status"] == "PUBLISHED" and ann["receipt_state"] in ("OPEN", "UPCOMING"),
            "companies": rows}


@dataclass
class _Out:
    message_id: int
    email: str
    subject: str
    body: str


def _mail(ann: dict, rec: dict, sender: dict, note: str | None, token: str) -> tuple[str, str]:
    period = " ~ ".join(d.isoformat() for d in (ann["receipt_start"], ann["receipt_end"]) if d) or "공고문 참고"
    lines = [
        f"{rec['company_name']} 담당자님께,",
        "",
        f"{ann['agency_name'] or '기관'} 담당자가 아래 공고 참여를 권해 드립니다.",
        "",
        f"공고: {ann['title']}",
        f"접수: {period}",
        f"판정: {COMPANY_VERDICT_KO[rec['verdict']]} (필수 조건 {rec['mandatory_met']}/{rec['mandatory_total']} 충족)",
    ]
    if note:
        lines += ["", "담당자 메모:", note.strip()]
    lines += [
        "",
        f"자세히 보기: {_base()}/navigator?brn={format_bizno(rec['business_reg_no'])}",
        "확인 필요 항목 답변은 위 화면의 '회사 정보 입력·수정'에서 할 수 있습니다.",
        "",
        f"보낸 사람: {sender['name']}{' (' + sender['department'] + ')' if sender.get('department') else ''}",
    ]
    if sender.get("email"):
        lines.append("이 메일에 회신하면 담당자에게 갑니다.")
    lines += ["", f"참여 권유 메일 그만 받기: {optout_url(token)}"]
    return f"[Navigator] 참여 권유: {ann['title']}", "\n".join(lines)


async def send(ann_id: int, org_ids: list[int], note: str | None, user_id: int,
               request_id: str | None = None) -> dict:
    """권유 메일 기록 → 커밋 → 발송 → 결과 기록. 메일 한 통 실패는 FAILED 로 남기고 넘어간다."""
    out: list[_Out] = []
    skipped: list[dict] = []
    async with transaction(user_id, request_id) as conn:
        ann = await (await conn.execute(
            """SELECT id, title, agency_name, receipt_start, receipt_end, status, receipt_state
                 FROM ax.v_announcement WHERE id = %s""", (ann_id,))).fetchone()
        if ann is None:
            raise NotFound("공고", ann_id)
        if ann["status"] != "PUBLISHED" or ann["receipt_state"] not in ("OPEN", "UPCOMING"):
            raise Conflict("공개된 접수중·접수 예정 공고에만 권유 메일을 보낼 수 있습니다")
        run_id = await _latest_run(conn, ann_id)
        if run_id is None:
            raise Conflict("이 공고로 기업 판정을 먼저 실행하세요")
        sender = await (await conn.execute(
            """SELECT u.name, u.email, d.name AS department FROM ax.app_user u
                 LEFT JOIN ax.department d ON d.id = u.department_id WHERE u.id = %s""", (user_id,))).fetchone()
        recs = {r["organization_id"]: r for r in await (await conn.execute(
            """SELECT cr.id, cr.organization_id, cr.verdict, cr.mandatory_met, cr.mandatory_total,
                      o.name AS company_name, o.business_reg_no, cp.registered_email,
                      cp.outreach_consent_at IS NOT NULL AS consent,
                      EXISTS (SELECT 1 FROM ax.outreach_message m WHERE m.announcement_id = %s
                                AND m.organization_id = cr.organization_id AND m.status <> 'FAILED') AS sent
                 FROM ax.company_recommendation cr
                 JOIN ax.organization o ON o.id = cr.organization_id
                 JOIN ax.company_profile cp ON cp.organization_id = cr.organization_id
                WHERE cr.match_run_id = %s AND cr.organization_id = ANY(%s)""",
            (ann_id, run_id, org_ids))).fetchall()}
        for org in dict.fromkeys(org_ids):
            r = recs.get(org)
            reason = ("NOT_IN_RESULT" if r is None else "INELIGIBLE" if r["verdict"] == "INELIGIBLE"
                      else "NO_CONSENT" if not r["consent"] else "NO_EMAIL" if not r["registered_email"]
                      else "ALREADY_SENT" if r["sent"] else None)
            if reason:
                skipped.append({"organization_id": org, "company_name": r["company_name"] if r else None,
                                "reason": reason, "reason_label": SKIP_KO[reason]})
                continue
            token = secrets.token_urlsafe(32)
            row = await (await conn.execute(
                """INSERT INTO ax.outreach_message (announcement_id, organization_id, recommendation_id, verdict,
                                                    email, note, optout_token_hash, sent_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (announcement_id, organization_id) DO UPDATE      -- 실패했던 것만 다시
                      SET recommendation_id = EXCLUDED.recommendation_id, verdict = EXCLUDED.verdict,
                          email = EXCLUDED.email, note = EXCLUDED.note, status = 'PENDING', error = NULL,
                          optout_token_hash = EXCLUDED.optout_token_hash, sent_by = EXCLUDED.sent_by,
                          created_at = now()
                    WHERE ax.outreach_message.status = 'FAILED'
                   RETURNING id""",
                (ann_id, org, r["id"], r["verdict"], r["registered_email"], note, hash_token(token),
                 user_id))).fetchone()
            if row is None:
                continue
            subject, body = _mail(ann, r, sender, note, token)
            out.append(_Out(row["id"], r["registered_email"], subject, body))

    results: list[tuple[int, str | None]] = []
    for m in out:
        try:
            await mailer.send_async(m.email, m.subject, m.body, reply_to=sender["email"])
            results.append((m.message_id, None))
        except Exception as e:  # noqa: BLE001
            log.warning("권유 메일 실패 message=%s: %s", m.message_id, e)
            results.append((m.message_id, str(e)[:500]))
    if results:
        async with transaction(user_id, request_id) as conn:
            for mid, err in results:
                await conn.execute(
                    """UPDATE ax.outreach_message
                          SET status = CASE WHEN %(err)s::text IS NULL THEN 'SENT' ELSE 'FAILED' END,
                              sent_at = CASE WHEN %(err)s::text IS NULL THEN now() END, error = %(err)s
                        WHERE id = %(id)s AND status = 'PENDING'""", {"err": err, "id": mid})
    failed = sum(err is not None for _, err in results)
    return {"announcement_id": ann_id, "sent": len(results) - failed, "failed": failed, "skipped": skipped}


async def optout(conn: AsyncConnection, token: str) -> dict | None:
    row = await (await conn.execute(
        """SELECT m.organization_id, m.email, o.name AS company_name
             FROM ax.outreach_message m JOIN ax.organization o ON o.id = m.organization_id
            WHERE m.optout_token_hash = %s""", (hash_token(token),))).fetchone()
    if row is None:
        return None
    await set_consent(conn, row["organization_id"], False)
    return {"company_name": row["company_name"], "email": mailer.mask_email(row["email"])}
