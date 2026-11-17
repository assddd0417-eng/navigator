"""공고 알림. 새 공고가 공개되면 구독 기업만 판정해서 화면 알림과 메일을 만든다."""
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
from app.services.navigator_matching import match_announcement

log = logging.getLogger("app.navigator_alerts")

MAX_SUBSCRIPTIONS = 5
CONFIRM_TTL_DAYS = 3
SUB_COLUMNS = ("id, email, keywords, min_score::float AS min_score, include_needs_info, channels, is_active, "
               "email_confirmed_at, unsubscribed_at, confirm_expires_at, created_at")


def _base() -> str:
    return get_settings().navigator_public_base_url.rstrip("/")


def confirm_url(token: str) -> str:
    return f"{_base()}/navigator/subscriptions/confirm#t={token}"


def unsubscribe_url(token: str) -> str:
    return f"{_base()}/navigator/unsubscribe#t={token}"


# 구독 관리 (관리 링크)

async def list_subscriptions(conn: AsyncConnection, org_id: int) -> list[dict]:
    return await (await conn.execute(
        f"SELECT {SUB_COLUMNS} FROM ax.alert_subscription WHERE organization_id = %s ORDER BY id", (org_id,))).fetchall()


async def get_subscription(conn: AsyncConnection, org_id: int, sub_id: int) -> dict:
    row = await (await conn.execute(
        f"SELECT {SUB_COLUMNS} FROM ax.alert_subscription WHERE id = %s AND organization_id = %s",
        (sub_id, org_id))).fetchone()
    if row is None:
        raise NotFound("알림 구독", sub_id)
    return row


async def create_subscription(conn: AsyncConnection, org_id: int, verified_email: str, data: dict) -> tuple[dict, str | None]:
    """관리 링크를 받은 이메일(이미 확인됨)이면 바로 시작, 다른 주소면 확인 메일 토큰을 돌려준다."""
    email = data["email"].strip().lower()
    n = await (await conn.execute(
        "SELECT count(*) AS n FROM ax.alert_subscription WHERE organization_id = %s", (org_id,))).fetchone()
    if n["n"] >= MAX_SUBSCRIPTIONS:
        raise Conflict(f"수신자는 {MAX_SUBSCRIPTIONS}명까지 등록할 수 있습니다")
    if await (await conn.execute(
            "SELECT 1 FROM ax.alert_subscription WHERE organization_id = %s AND email = %s", (org_id, email))).fetchone():
        raise Conflict("이미 등록된 수신자입니다")
    token = None if email == verified_email.lower() else secrets.token_urlsafe(32)
    row = await (await conn.execute(
        """INSERT INTO ax.alert_subscription (organization_id, email, keywords, min_score, include_needs_info, channels,
                                              confirm_token_hash, confirm_expires_at, email_confirmed_at)
           VALUES (%(org)s, %(email)s, %(keywords)s, %(min_score)s, %(include_needs_info)s, %(channels)s,
                   %(hash)s, CASE WHEN %(hash)s::text IS NOT NULL THEN now() + make_interval(days => %(ttl)s) END,
                   CASE WHEN %(hash)s::text IS NULL THEN now() END)
           RETURNING id""",
        {"org": org_id, "email": email, "keywords": data["keywords"], "min_score": data["min_score"],
         "include_needs_info": data["include_needs_info"], "channels": data["channels"],
         "hash": hash_token(token) if token else None, "ttl": CONFIRM_TTL_DAYS})).fetchone()
    return await get_subscription(conn, org_id, row["id"]), token


async def subscribe_registered_email(conn: AsyncConnection, org_id: int, email: str) -> None:
    """등록 이메일을 기본 설정(관심 분야 없음, 확인 필요 포함, 화면+메일)으로 바로 구독. 이미 있으면 그대로 둔다."""
    await conn.execute(
        """INSERT INTO ax.alert_subscription (organization_id, email, keywords, min_score, include_needs_info, channels,
                                              email_confirmed_at)
           SELECT %(org)s, %(email)s, '{}', 0, true, ARRAY['SCREEN', 'EMAIL'], now()
            WHERE NOT EXISTS (SELECT 1 FROM ax.alert_subscription WHERE organization_id = %(org)s AND email = %(email)s)
              AND (SELECT count(*) FROM ax.alert_subscription WHERE organization_id = %(org)s) < %(max)s""",
        {"org": org_id, "email": email.strip().lower(), "max": MAX_SUBSCRIPTIONS})


async def update_subscription(conn: AsyncConnection, org_id: int, sub_id: int, data: dict) -> dict:
    await get_subscription(conn, org_id, sub_id)
    if data:
        sets = ", ".join(f"{k} = %({k})s" for k in data)
        await conn.execute(f"UPDATE ax.alert_subscription SET {sets}, updated_at = now() WHERE id = %(id)s",
                           {**data, "id": sub_id})
    return await get_subscription(conn, org_id, sub_id)


async def delete_subscription(conn: AsyncConnection, org_id: int, sub_id: int) -> None:
    cur = await conn.execute("DELETE FROM ax.alert_subscription WHERE id = %s AND organization_id = %s",
                             (sub_id, org_id))
    if cur.rowcount == 0:
        raise NotFound("알림 구독", sub_id)


async def renew_confirm_token(conn: AsyncConnection, org_id: int, sub_id: int) -> tuple[dict, str]:
    """확인 메일 재발송. 수신자가 해지한 구독도 수신자가 다시 확인해야 살아난다."""
    sub = await get_subscription(conn, org_id, sub_id)
    if sub["email_confirmed_at"] and not sub["unsubscribed_at"]:
        raise Conflict("이미 확인된 수신자입니다")
    token = secrets.token_urlsafe(32)
    await conn.execute(
        """UPDATE ax.alert_subscription
              SET confirm_token_hash = %s, confirm_expires_at = now() + make_interval(days => %s), updated_at = now()
            WHERE id = %s""", (hash_token(token), CONFIRM_TTL_DAYS, sub_id))
    return await get_subscription(conn, org_id, sub_id), token


async def send_confirm_mail(email: str, company_name: str, token: str) -> None:
    await mailer.send_async(email, f"[Navigator] {company_name} 공고 알림 수신 확인",
                f"{company_name}에서 이 주소로 새 공고 알림을 받도록 신청했습니다.\n\n"
                f"받으시려면 {CONFIRM_TTL_DAYS}일 안에 아래 주소를 여세요.\n{confirm_url(token)}\n\n"
                "신청한 적이 없다면 이 메일을 무시하세요. 확인하지 않으면 알림은 가지 않습니다.")


async def confirm(conn: AsyncConnection, token: str) -> dict | None:
    if not token or len(token) > 200:
        return None
    return await (await conn.execute(
        """UPDATE ax.alert_subscription s
              SET email_confirmed_at = now(), confirm_token_hash = NULL, confirm_expires_at = NULL,
                  unsubscribed_at = NULL, updated_at = now()
             FROM ax.organization o
            WHERE o.id = s.organization_id AND s.confirm_token_hash = %s AND s.confirm_expires_at > now()
        RETURNING s.id, s.email, o.name AS company_name""", (hash_token(token),))).fetchone()


async def unsubscribe(conn: AsyncConnection, token: str) -> dict | None:
    if not token or len(token) > 200:
        return None
    return await (await conn.execute(
        """UPDATE ax.alert_subscription s
              SET unsubscribed_at = COALESCE(s.unsubscribed_at, now()), updated_at = now()
             FROM ax.alert_notification n, ax.organization o
            WHERE n.unsubscribe_token_hash = %s AND s.id = n.subscription_id AND o.id = s.organization_id
        RETURNING s.id, s.email, o.name AS company_name""", (hash_token(token),))).fetchone()


# 화면 알림

async def list_alerts(conn: AsyncConnection, org_id: int, limit: int = 50) -> dict:
    # 수신자가 여럿이어도 화면에는 공고당 하나
    rows = await (await conn.execute(
        """SELECT * FROM (
             SELECT DISTINCT ON (n.announcement_id)
                    n.announcement_id, a.title AS announcement_title, a.agency_name, a.receipt_end, a.receipt_state,
                    n.verdict, n.total_score::float AS total_score, n.rationale, n.created_at,
                    bool_or(n.read_at IS NOT NULL) OVER (PARTITION BY n.announcement_id) AS is_read
               FROM ax.alert_notification n
               JOIN ax.alert_subscription s ON s.id = n.subscription_id
               JOIN ax.v_announcement a ON a.id = n.announcement_id
              WHERE n.organization_id = %s AND 'SCREEN' = ANY(s.channels)
              ORDER BY n.announcement_id, n.created_at) x
           ORDER BY created_at DESC LIMIT %s""", (org_id, limit))).fetchall()
    for r in rows:
        r["verdict_label"] = COMPANY_VERDICT_KO[r["verdict"]]
    return {"unread": sum(not r["is_read"] for r in rows), "alerts": rows}


async def mark_read(conn: AsyncConnection, org_id: int, announcement_ids: list[int] | None) -> None:
    await conn.execute(
        """UPDATE ax.alert_notification SET read_at = now(), status = 'READ'
            WHERE organization_id = %s AND read_at IS NULL
              AND (%s::bigint[] IS NULL OR announcement_id = ANY(%s))""",
        (org_id, announcement_ids, announcement_ids))


# 발송

@dataclass
class Outgoing:
    notification_id: int
    email: str
    subject: str
    body: str


def _keyword_hit(keywords: list[str], text: str) -> bool:
    return not keywords or any(k.strip().lower() in text for k in keywords if k.strip())


def _mail(ann: dict, rec: dict, token: str) -> tuple[str, str]:
    verdict = COMPANY_VERDICT_KO[rec["verdict"]]
    subject = f"[Navigator] 새 공고 ({verdict}): {ann['title']}"
    deadline = ann["receipt_end"].isoformat() if ann["receipt_end"] else "미정"
    body = (f"{rec['name']}에 맞는 새 공고가 등록되었습니다.\n\n"
            f"공고: {ann['title']}\n기관: {ann['agency_name']}\n접수 마감: {deadline}\n"
            f"판정: {verdict}\n{rec['rationale']}\n\n"
            f"자세히 보기: {_base()}/navigator?brn={format_bizno(rec['business_reg_no'])}\n"
            "확인 필요 항목 답변과 신용등급 조건은 위 화면의 '회사 정보 입력·수정'에서 확인하세요.\n\n"
            f"알림 그만 받기: {unsubscribe_url(token)}")
    return subject, body


async def _prepare(conn: AsyncConnection, ann_id: int) -> tuple[int | None, list[Outgoing], int]:
    ann = await (await conn.execute(
        "SELECT id, title, agency_name, summary, receipt_end, status, receipt_state FROM ax.v_announcement "
        "WHERE id = %s", (ann_id,))).fetchone()
    if ann is None:
        raise NotFound("공고", ann_id)
    if ann["status"] != "PUBLISHED" or ann["receipt_state"] not in ("OPEN", "UPCOMING"):
        return None, [], 0
    # 이 공고 알림을 아직 안 받은 구독만
    subs = await (await conn.execute(
        """SELECT s.id, s.organization_id, s.email, s.keywords, s.min_score::float AS min_score,
                  s.include_needs_info, s.channels
             FROM ax.alert_subscription s
             JOIN ax.organization o ON o.id = s.organization_id AND o.is_active
            WHERE s.is_active AND s.email_confirmed_at IS NOT NULL AND s.unsubscribed_at IS NULL
              AND NOT EXISTS (SELECT 1 FROM ax.alert_notification n
                               WHERE n.subscription_id = s.id AND n.announcement_id = %s)
            ORDER BY s.id""", (ann_id,))).fetchall()
    if not subs:
        return None, [], 0
    run_id = await match_announcement(conn, ann_id, requested_by=None, via="SYSTEM",
                                      org_ids=[s["organization_id"] for s in subs])
    recs = {r["organization_id"]: r for r in await (await conn.execute(
        """SELECT cr.id, cr.organization_id, cr.verdict, cr.total_score, cr.rationale, o.name, o.business_reg_no
             FROM ax.company_recommendation cr JOIN ax.organization o ON o.id = cr.organization_id
            WHERE cr.match_run_id = %s""", (run_id,))).fetchall()}
    tech = await (await conn.execute(
        "SELECT string_agg(tech_name, ' ') AS t FROM ax.announcement_tech_need WHERE announcement_id = %s",
        (ann_id,))).fetchone()
    text = " ".join(x for x in (ann["title"], ann["summary"], tech["t"]) if x).lower()

    out: list[Outgoing] = []
    created = 0
    for s in subs:
        rec = recs.get(s["organization_id"])
        if (rec is None or rec["verdict"] == "INELIGIBLE"
                or (rec["verdict"] == "NEEDS_INFO" and not s["include_needs_info"])
                or float(rec["total_score"]) < s["min_score"] or not _keyword_hit(s["keywords"], text)):
            continue
        token = secrets.token_urlsafe(32) if "EMAIL" in s["channels"] else None
        row = await (await conn.execute(
            """INSERT INTO ax.alert_notification (subscription_id, organization_id, announcement_id, recommendation_id,
                                                  verdict, total_score, rationale, status, sent_at,
                                                  unsubscribe_token_hash)
               VALUES (%(sub)s, %(org)s, %(ann)s, %(rec)s, %(verdict)s, %(score)s, %(rationale)s,
                       CASE WHEN %(email)s THEN 'PENDING' ELSE 'SENT' END,
                       CASE WHEN %(email)s THEN NULL ELSE now() END, %(hash)s)
               ON CONFLICT (subscription_id, announcement_id) DO NOTHING RETURNING id""",
            {"sub": s["id"], "org": s["organization_id"], "ann": ann_id, "rec": rec["id"], "verdict": rec["verdict"],
             "score": rec["total_score"], "rationale": rec["rationale"], "email": token is not None,
             "hash": hash_token(token) if token else None})).fetchone()
        if row is None:
            continue
        created += 1
        if token:
            subject, body = _mail(ann, rec, token)
            out.append(Outgoing(row["id"], s["email"], subject, body))
    return run_id, out, created


async def dispatch_for_announcement(ann_id: int, request_id: str | None = None) -> dict:
    """알림 생성 → 커밋 → 메일 발송 → 결과 기록. 메일 실패는 FAILED 로 남기고 넘어간다."""
    async with transaction(None, request_id) as conn:
        run_id, outgoing, created = await _prepare(conn, ann_id)
    results: list[tuple[int, str | None]] = []
    for m in outgoing:
        try:
            await mailer.send_async(m.email, m.subject, m.body)
            results.append((m.notification_id, None))
        except Exception as e:  # noqa: BLE001  메일 한 통 실패가 나머지를 막지 않게
            log.warning("알림 메일 실패 notification=%s: %s", m.notification_id, e)
            results.append((m.notification_id, str(e)[:500]))
    if results:
        async with transaction(None, request_id) as conn:
            for nid, err in results:
                await conn.execute(
                    """UPDATE ax.alert_notification
                          SET status = CASE WHEN %(err)s::text IS NULL THEN 'SENT' ELSE 'FAILED' END,
                              sent_at = CASE WHEN %(err)s::text IS NULL THEN now() END, error = %(err)s
                        WHERE id = %(id)s AND status = 'PENDING'""", {"err": err, "id": nid})
    failed = sum(err is not None for _, err in results)
    return {"announcement_id": ann_id, "match_run_id": run_id, "notifications": created,
            "emails_sent": len(results) - failed, "emails_failed": failed}


async def safe_dispatch(ann_id: int, request_id: str | None = None) -> dict | None:
    """공고 저장은 이미 끝났으니 알림 실패로 요청을 실패시키지 않는다."""
    try:
        return await dispatch_for_announcement(ann_id, request_id)
    except Exception:  # noqa: BLE001
        log.exception("공고 %s 알림 처리 실패", ann_id)
        return None


async def announcement_alerts(conn: AsyncConnection, ann_id: int) -> dict:
    rows = await (await conn.execute(
        """SELECT n.id, o.name AS company_name, s.email, n.verdict, n.total_score::float AS total_score, n.status,
                  n.created_at, n.sent_at, n.read_at, s.channels
             FROM ax.alert_notification n
             JOIN ax.organization o ON o.id = n.organization_id
             JOIN ax.alert_subscription s ON s.id = n.subscription_id
            WHERE n.announcement_id = %s ORDER BY n.created_at, n.id""", (ann_id,))).fetchall()
    for r in rows:
        r["verdict_label"] = VERDICT_KO[r["verdict"]]
        r["email"] = mailer.mask_email(r["email"])
    live = await (await conn.execute(
        """SELECT count(DISTINCT organization_id) AS n FROM ax.alert_subscription
            WHERE is_active AND email_confirmed_at IS NOT NULL AND unsubscribed_at IS NULL""")).fetchone()
    return {"subscribed_companies": live["n"], "notifications": rows}
