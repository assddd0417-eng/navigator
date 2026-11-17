"""Navigator 공고 알림 API. /manage/* 는 관리 링크, /subscriptions/* 는 메일 링크, /alerts/* 는 담당자."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator

from app.auth import CurrentUser, request_id, require_roles
from app.config import get_settings
from app.db import transaction
from app.routers.navigator import manage_link
from app.schemas.navigator import EMAIL_PATTERN
from app.services import mailer
from app.services import navigator_outreach as outreach
from app.services import navigator_alerts as alerts
from app.services.ratelimit import public_rate_limit

router = APIRouter(prefix="/navigator", tags=["Navigator 알림"])
STAFF = ("STAFF",)
Channel = Literal["SCREEN", "EMAIL"]


def _clean_keywords(v: list[str] | None) -> list[str] | None:
    if v is None:
        return None
    out: list[str] = []
    for k in (x.strip() for x in v):
        if len(k) > 50:
            raise ValueError("관심 분야는 50자 이내")
        if k and k not in out:
            out.append(k)
    return out


def _uniq_channels(v: list[str] | None) -> list[str] | None:
    return None if v is None else sorted(set(v), reverse=True)


class SubscriptionIn(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=200)
    keywords: list[str] = Field(default=[], max_length=20)
    min_score: float = Field(default=0, ge=0, le=1)
    include_needs_info: bool = True
    channels: list[Channel] = Field(default=["SCREEN", "EMAIL"], min_length=1)

    _k = field_validator("keywords")(_clean_keywords)
    _c = field_validator("channels")(_uniq_channels)


class SubscriptionUpdate(BaseModel):
    keywords: list[str] | None = Field(default=None, max_length=20)
    min_score: float | None = Field(default=None, ge=0, le=1)
    include_needs_info: bool | None = None
    channels: list[Channel] | None = Field(default=None, min_length=1)
    is_active: bool | None = None

    _k = field_validator("keywords")(_clean_keywords)
    _c = field_validator("channels")(_uniq_channels)


class TokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class ReadIn(BaseModel):
    announcement_ids: list[int] | None = None


async def _with_confirm(sub: dict, token: str | None, email: str, company_name: str) -> dict:
    if token:
        try:
            await alerts.send_confirm_mail(email, company_name, token)
        except mailer.MailError:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                                "확인 메일을 보내지 못했습니다. 잠시 후 '확인 메일 다시 보내기'를 눌러 주세요") from None
    sub["confirm_sent"] = token is not None
    sub["dev_confirm_link"] = alerts.confirm_url(token) if token and get_settings().navigator_dev_expose_link else None
    return sub


async def _company_name(conn, org_id: int) -> str:
    return (await (await conn.execute("SELECT name FROM ax.organization WHERE id = %s", (org_id,))).fetchone())["name"]


@router.get("/manage/subscriptions", dependencies=[Depends(public_rate_limit)])
async def my_subscriptions(link: dict = Depends(manage_link)):
    async with transaction() as conn:
        return {"registered_email": link["email"], "max": alerts.MAX_SUBSCRIPTIONS,
                "subscriptions": await alerts.list_subscriptions(conn, link["organization_id"])}


@router.post("/manage/subscriptions", status_code=201, dependencies=[Depends(public_rate_limit)])
async def add_subscription(body: SubscriptionIn, link: dict = Depends(manage_link), rid: str = Depends(request_id)):
    """관리 링크를 받은 주소는 바로 시작. 다른 주소는 그 주소로 확인 메일을 보내고, 확인 후 시작."""
    org_id = link["organization_id"]
    async with transaction(None, f"{rid}|company-link:{link['link_id']}") as conn:
        sub, token = await alerts.create_subscription(conn, org_id, link["email"], body.model_dump())
        name = await _company_name(conn, org_id)
    return await _with_confirm(sub, token, sub["email"], name)


@router.patch("/manage/subscriptions/{sub_id}", dependencies=[Depends(public_rate_limit)])
async def edit_subscription(sub_id: int, body: SubscriptionUpdate, link: dict = Depends(manage_link),
                            rid: str = Depends(request_id)):
    async with transaction(None, f"{rid}|company-link:{link['link_id']}") as conn:
        return await alerts.update_subscription(conn, link["organization_id"], sub_id,
                                                body.model_dump(exclude_unset=True, exclude_none=True))


@router.delete("/manage/subscriptions/{sub_id}", status_code=204, dependencies=[Depends(public_rate_limit)])
async def remove_subscription(sub_id: int, link: dict = Depends(manage_link), rid: str = Depends(request_id)):
    async with transaction(None, f"{rid}|company-link:{link['link_id']}") as conn:
        await alerts.delete_subscription(conn, link["organization_id"], sub_id)
    return Response(status_code=204)


@router.post("/manage/subscriptions/{sub_id}/confirm-mail", dependencies=[Depends(public_rate_limit)])
async def resend_confirm(sub_id: int, link: dict = Depends(manage_link), rid: str = Depends(request_id)):
    org_id = link["organization_id"]
    async with transaction(None, f"{rid}|company-link:{link['link_id']}") as conn:
        sub, token = await alerts.renew_confirm_token(conn, org_id, sub_id)
        name = await _company_name(conn, org_id)
    return await _with_confirm(sub, token, sub["email"], name)


@router.get("/manage/alerts", dependencies=[Depends(public_rate_limit)])
async def my_alerts(link: dict = Depends(manage_link)):
    async with transaction() as conn:
        return await alerts.list_alerts(conn, link["organization_id"])


@router.post("/manage/alerts/read", status_code=204, dependencies=[Depends(public_rate_limit)])
async def read_alerts(body: ReadIn, link: dict = Depends(manage_link)):
    async with transaction() as conn:
        await alerts.mark_read(conn, link["organization_id"], body.announcement_ids)
    return Response(status_code=204)


@router.post("/subscriptions/confirm", dependencies=[Depends(public_rate_limit)])
async def confirm_subscription(body: TokenIn, rid: str = Depends(request_id)):
    async with transaction(None, rid) as conn:
        row = await alerts.confirm(conn, body.token)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "확인 링크가 만료되었거나 잘못되었습니다. 신청한 회사에 다시 요청하세요")
    return {"company_name": row["company_name"], "email": mailer.mask_email(row["email"])}


@router.post("/subscriptions/unsubscribe", dependencies=[Depends(public_rate_limit)])
async def unsubscribe(body: TokenIn, rid: str = Depends(request_id)):
    async with transaction(None, rid) as conn:
        row = await alerts.unsubscribe(conn, body.token)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "해지 링크가 잘못되었습니다")
    return {"company_name": row["company_name"], "email": mailer.mask_email(row["email"])}


class ConsentIn(BaseModel):
    consent: bool


@router.put("/manage/outreach-consent", dependencies=[Depends(public_rate_limit)])
async def set_outreach_consent(body: ConsentIn, link: dict = Depends(manage_link), rid: str = Depends(request_id)):
    """기관 담당자의 참여 권유 메일 받기 (등록 이메일로)."""
    async with transaction(None, f"{rid}|company-link:{link['link_id']}") as conn:
        return await outreach.set_consent(conn, link["organization_id"], body.consent)


@router.post("/outreach/optout", dependencies=[Depends(public_rate_limit)])
async def outreach_optout(body: TokenIn, rid: str = Depends(request_id)):
    async with transaction(None, rid) as conn:
        row = await outreach.optout(conn, body.token)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "수신 거부 링크가 잘못되었습니다")
    return row


@router.get("/alerts/announcements/{ann_id}")
async def announcement_alerts(ann_id: int, _: CurrentUser = Depends(require_roles(*STAFF))):
    async with transaction() as conn:
        return await alerts.announcement_alerts(conn, ann_id)


@router.post("/alerts/announcements/{ann_id}")
async def dispatch_alerts(ann_id: int, _: CurrentUser = Depends(require_roles(*STAFF)),
                          rid: str = Depends(request_id)):
    """아직 이 공고 알림을 안 받은 구독 기업에만 보낸다 (중복 발송 없음)."""
    return await alerts.dispatch_for_announcement(ann_id, rid)
