"""Navigator 기업 프로필 (공개 API). 수정·민감정보 조회는 관리 링크(X-Manage-Token) 필요."""
import hashlib
import logging
from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, File, Header, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from app.auth import request_id
from app.config import get_settings
from app.db import transaction
from app.errors import Conflict
from app.schemas.navigator import CompanyRegister, CompanyUpdate, LinkSent, RegisterResult
from app.services import access_link, collector, company_evidence, login_code, mailer, navigator_alerts
from app.services.bizno import InvalidBizNo, format_bizno, normalize
from app.services.company_profile import (
    BUSINESS_STATUS_LABEL, LIST_TABLES, PROFILE_FIELDS, VERIFY_LABEL, find_by_bizno, full_view,
    insert_list_items, public_view, record_field, replace_self_items)
from app.services.external import BizVerifyResult, ConnectorUnavailable, get_nts_connector, record_fetch
from app.services.external.nts import SOURCE_CODE as NTS
from app.services.navigator_embedding import fit_levels, sync_company_embeddings
from app.services.ratelimit import public_rate_limit

router = APIRouter(prefix="/navigator", tags=["Navigator 기업 프로필 (로그인 없음)"])
log = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))


def _bizno(raw: str) -> str:
    try:
        return normalize(raw)
    except InvalidBizNo as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None


async def _send_link(email: str, company_name: str, link: access_link.IssuedLink, first: bool) -> LinkSent:
    if first:   # 등록 메일은 알림 주소 확인용. 회사 정보는 화면에서 바로 입력하므로 링크를 넣지 않는다
        try:    # 등록은 이미 저장됐으니 메일 실패로 요청을 실패시키지 않는다
            await mailer.send_async(email, f"[Navigator] {company_name} 등록 완료",
                                    f"{company_name} 등록이 완료되었습니다.\n조건에 맞는 새 공고가 올라오면 이 주소로 알려 드립니다.\n"
                                    "본인이 등록하지 않았다면 이 메일을 무시하세요.")
        except mailer.MailError as e:
            log.warning("등록 메일 실패: %s", e)
        return LinkSent(sent_to=mailer.mask_email(email), expires_at=link.expires_at.isoformat(),
                        dev_management_link=link.url if get_settings().navigator_dev_expose_link else None)
    until = link.expires_at.astimezone(KST)
    try:
        await mailer.send_async(email, f"[Navigator] {company_name} 회사 정보 화면 링크",
                                f"{company_name} 회사 정보 화면 링크입니다.\n\n아래 주소에서 회사 정보를 고치고 신용정보를 볼 수 있습니다.\n"
                                f"{link.url}\n\n{until:%Y-%m-%d %H:%M}까지 열 수 있습니다. "
                                "기간이 지나면 사업자번호로 다시 요청하세요.\n본인이 요청하지 않았다면 이 메일을 무시하세요.")
    except mailer.MailError as e:
        log.warning("관리 링크 메일 실패: %s", e)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "메일을 보내지 못했습니다. 잠시 후 다시 시도하세요") from None
    return LinkSent(sent_to=mailer.mask_email(email), expires_at=link.expires_at.isoformat(),
                    dev_management_link=link.url if get_settings().navigator_dev_expose_link else None)


def _verify(body: CompanyRegister, bizno: str) -> tuple[BizVerifyResult, str, str | None]:
    mode = get_settings().source_nts_biz.lower()
    try:
        connector = get_nts_connector()
        return connector.verify(bizno, body.representative_name, body.opened_on), connector.mode, None
    except ConnectorUnavailable as e:
        return BizVerifyResult("UNVERIFIED", "UNKNOWN", f"국세청 진위확인을 할 수 없어 미확인으로 저장합니다 ({e})"), \
            mode, str(e)


@router.post("/companies", response_model=RegisterResult, status_code=201,
             dependencies=[Depends(public_rate_limit)])
async def register_company(body: CompanyRegister, rid: str = Depends(request_id)):
    """진위확인 불일치면 422. 확인 불가면 미확인으로 저장. 기존 기관 DB 기업은 진위확인 통과해야 등록."""
    bizno = _bizno(body.business_reg_no)
    result, mode, conn_error = _verify(body, bizno)
    params = {"b_no": bizno}

    if result.verify_status == "FAILED":
        async with transaction(None, rid) as conn:   # 거절해도 수집 기록은 남긴다
            await record_fetch(conn, source_code=NTS, mode=mode, organization_id=None, external_key=bizno,
                               payload=result.raw, trigger_kind="REGISTRATION", request_params=params)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"국세청 진위확인 불일치: {result.message}. 사업자등록증의 대표자명·개업일을 확인하세요")

    async with transaction(None, rid) as conn:
        existing = await find_by_bizno(conn, bizno, lock=True)
        if existing:
            if existing["org_type"] != "COMPANY":
                raise Conflict("이 사업자번호는 기업이 아닌 기관으로 등록되어 있습니다. 기관 담당자에게 문의하세요")
            if existing["registered_email"]:
                raise Conflict("이미 등록된 사업자번호입니다. 등록 이메일로 관리 링크를 다시 요청하세요 "
                               f"(POST /navigator/companies/{bizno}/access-link)")
            if result.verify_status != "VERIFIED":
                raise Conflict("기관 DB 에 이미 있는 기업입니다. 국세청 진위확인을 통과해야 이어서 등록할 수 있습니다")
            org_id = existing["organization_id"]
            await conn.execute("UPDATE ax.organization SET name = %s WHERE id = %s", (body.company_name, org_id))
        else:
            org = await (await conn.execute(
                "INSERT INTO ax.organization (name, org_type, business_reg_no) VALUES (%s, 'COMPANY', %s) RETURNING id",
                (body.company_name, bizno))).fetchone()
            org_id = org["id"]

        fields = {f: getattr(body, f) for f in PROFILE_FIELDS}
        verified = result.verify_status == "VERIFIED"
        cols = ["representative_name", "opened_on", *PROFILE_FIELDS]
        await conn.execute(
            f"""INSERT INTO ax.company_profile
                       (organization_id, {", ".join(cols)}, business_status, business_status_checked_at,
                        biz_verify_status, biz_verified_at, registered_email, registration_channel)
                VALUES (%(org)s, {", ".join(f"%({c})s" for c in cols)}, %(bstat)s,
                        CASE WHEN %(bstat)s <> 'UNKNOWN' THEN now() END,
                        %(vstat)s, CASE WHEN %(ver)s THEN now() END, %(email)s, 'SELF')
                ON CONFLICT (organization_id) DO UPDATE SET
                  {", ".join(f"{c} = COALESCE(EXCLUDED.{c}, company_profile.{c})" for c in cols)},
                  business_status = EXCLUDED.business_status,
                  business_status_checked_at = EXCLUDED.business_status_checked_at,
                  biz_verify_status = EXCLUDED.biz_verify_status, biz_verified_at = EXCLUDED.biz_verified_at,
                  registered_email = EXCLUDED.registered_email,
                  registration_channel = COALESCE(company_profile.registration_channel, 'SELF')""",
            {"org": org_id, "representative_name": body.representative_name, "opened_on": body.opened_on,
             **fields, "bstat": result.business_status, "vstat": result.verify_status, "ver": verified,
             "email": body.email})

        await record_field(conn, org_id, "company_name", body.company_name, "SELF")
        await record_field(conn, org_id, "representative_name", body.representative_name, "SELF")
        await record_field(conn, org_id, "opened_on", body.opened_on, "SELF")
        for f, v in fields.items():
            if v is not None:
                await record_field(conn, org_id, f, v, "SELF")
        raw_id = await record_fetch(conn, source_code=NTS, mode=mode, organization_id=org_id, external_key=bizno,
                                    payload=result.raw or None, error=conn_error, trigger_kind="REGISTRATION",
                                    request_params=params)
        if raw_id is not None:
            await record_field(conn, org_id, "business_status", result.business_status, "EXTERNAL",
                               source_code=NTS, raw_record_id=raw_id, verified=result.business_status != "UNKNOWN")
            if verified:
                for f, v in (("representative_name", body.representative_name), ("opened_on", body.opened_on)):
                    await record_field(conn, org_id, f, v, "EXTERNAL", source_code=NTS, raw_record_id=raw_id,
                                       verified=True)

        for key in LIST_TABLES:
            await insert_list_items(conn, org_id, key, getattr(body, key))
        await sync_company_embeddings(conn, org_id)
        link = await access_link.issue(conn, org_id, body.email)
        await navigator_alerts.subscribe_registered_email(conn, org_id, body.email)

    sent = await _send_link(body.email, body.company_name, link, first=True)
    return RegisterResult(
        organization_id=org_id, business_reg_no=format_bizno(bizno),
        biz_verify_status=result.verify_status, biz_verify_label=VERIFY_LABEL[result.verify_status],
        business_status=BUSINESS_STATUS_LABEL[result.business_status], message=result.message,
        manage_token=link.token, **sent.model_dump())


@router.get("/fit-levels")
async def get_fit_levels():
    """관련도 높음·보통 경계. 화면 표시와 알림 조건에 쓴다 (임베더마다 다름)."""
    return fit_levels()


@router.get("/companies/{business_reg_no}", dependencies=[Depends(public_rate_limit)])
async def get_company_public(business_reg_no: str):
    bizno = _bizno(business_reg_no)
    async with transaction() as conn:
        found = await find_by_bizno(conn, bizno)
        if not found or not found["has_profile"] or found["org_type"] != "COMPANY":
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"사업자번호 {format_bizno(bizno)} 로 등록된 기업이 없습니다")
        return await public_view(conn, found["organization_id"])


@router.post("/companies/{business_reg_no}/access-link", response_model=LinkSent, status_code=202,
             dependencies=[Depends(public_rate_limit)])
async def resend_access_link(business_reg_no: str, rid: str = Depends(request_id)):
    bizno = _bizno(business_reg_no)
    async with transaction(None, rid) as conn:
        found = await find_by_bizno(conn, bizno, lock=True)
        if not found or not found["registered_email"]:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                f"사업자번호 {format_bizno(bizno)} 로 등록(이메일 포함)된 기업이 없습니다")
        link = await access_link.issue(conn, found["organization_id"], found["registered_email"])
    return await _send_link(found["registered_email"], found["name"], link, first=False)


class LoginCodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


async def _company_for_login(conn, bizno: str) -> dict:
    found = await find_by_bizno(conn, bizno, lock=True)
    if not found or not found["has_profile"] or found["org_type"] != "COMPANY":
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"사업자번호 {format_bizno(bizno)} 로 등록된 기업이 없습니다")
    if not found["registered_email"]:
        raise Conflict("등록 이메일이 없는 기업입니다. 기관 담당자에게 이메일 등록을 요청하세요")
    return found


@router.post("/companies/{business_reg_no}/login-code", status_code=202, dependencies=[Depends(public_rate_limit)])
async def send_login_code(business_reg_no: str, rid: str = Depends(request_id)):
    """회사 정보 화면을 열 확인 코드를 등록 이메일로 보낸다 (10분 유효, 1분에 한 번)."""
    bizno = _bizno(business_reg_no)
    async with transaction(None, rid) as conn:
        found = await _company_for_login(conn, bizno)
        try:
            issued = await login_code.issue(conn, found["organization_id"], found["registered_email"])
        except login_code.TooSoon as e:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"{e.wait_s}초 뒤에 다시 받을 수 있습니다",
                                headers={"Retry-After": str(e.wait_s)}) from None
    email = found["registered_email"]
    try:
        await mailer.send_async(email, f"[Navigator] 확인 코드 {issued.code}",
                                f"{found['name']} 회사 정보 화면 확인 코드입니다.\n\n{issued.code}\n\n"
                                f"{login_code.TTL_MINUTES}분 안에 화면에 넣으세요. 본인이 요청하지 않았다면 이 메일을 무시하세요.")
    except mailer.MailError as e:
        log.warning("확인 코드 메일 실패: %s", e)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "메일을 보내지 못했습니다. 잠시 후 다시 시도하세요") from None
    out = {"sent_to": mailer.mask_email(email), "expires_at": issued.expires_at.isoformat()}
    if get_settings().navigator_dev_expose_link:
        out["dev_code"] = issued.code
    return out


@router.post("/companies/{business_reg_no}/login", dependencies=[Depends(public_rate_limit)])
async def login_with_code(business_reg_no: str, body: LoginCodeIn, rid: str = Depends(request_id)):
    """확인 코드가 맞으면 관리 토큰을 준다 (이전 토큰은 폐기)."""
    bizno = _bizno(business_reg_no)
    async with transaction(None, rid) as conn:
        found = await _company_for_login(conn, bizno)
        result = await login_code.verify(conn, found["organization_id"], body.code)
        if result == "OK":
            link = await access_link.issue(conn, found["organization_id"], found["registered_email"])
    if result == "WRONG":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "확인 코드가 맞지 않습니다")
    if result == "EXPIRED":
        raise HTTPException(status.HTTP_410_GONE, "확인 코드가 만료되었습니다. 코드를 다시 받으세요")
    return {"token": link.token, "expires_at": link.expires_at.isoformat()}


async def manage_link(x_manage_token: str | None = Header(default=None, description="관리 링크의 비밀값")) -> dict:
    if not x_manage_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "관리 링크(X-Manage-Token)가 필요합니다")
    async with transaction() as conn:
        link = await access_link.resolve(conn, x_manage_token)
    if link is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "관리 링크가 만료되었거나 잘못되었습니다. 사업자번호로 관리 링크를 다시 요청하세요")
    return link


@router.get("/manage/profile", dependencies=[Depends(public_rate_limit)])
async def get_my_profile(link: dict = Depends(manage_link)):
    async with transaction() as conn:
        view = await full_view(conn, link["organization_id"])
    view["access_link"] = {"expires_at": link["expires_at"]}
    return view


@router.patch("/manage/profile", dependencies=[Depends(public_rate_limit)])
async def update_my_profile(body: CompanyUpdate, link: dict = Depends(manage_link), rid: str = Depends(request_id)):
    """보낸 칸만 수정 (자가입력으로 기록). 사업자번호·대표자명·개업일은 수정 불가."""
    org_id = link["organization_id"]
    data = body.model_dump(exclude_unset=True)
    # 기업은 app_user 가 없어서 감사 로그 추적용으로 링크 id 를 request_id 에 붙임
    async with transaction(None, f"{rid}|company-link:{link['link_id']}") as conn:
        if "company_name" in data and data["company_name"]:
            await conn.execute("UPDATE ax.organization SET name = %s WHERE id = %s", (data["company_name"], org_id))
            await record_field(conn, org_id, "company_name", data["company_name"], "SELF")
        fields = {f: data[f] for f in PROFILE_FIELDS if f in data}
        if fields:
            await conn.execute(
                f"UPDATE ax.company_profile SET {', '.join(f'{f} = %({f})s' for f in fields)} "
                "WHERE organization_id = %(org)s", {**fields, "org": org_id})
            for f, v in fields.items():
                await record_field(conn, org_id, f, v, "SELF")
        for key in LIST_TABLES:
            items = getattr(body, key)
            if items is not None:
                await replace_self_items(conn, org_id, key, items)
        # 매칭 캐시 무효화용
        await conn.execute("UPDATE ax.company_profile SET updated_at = now() WHERE organization_id = %s", (org_id,))
        await sync_company_embeddings(conn, org_id)
        return await full_view(conn, org_id)


AUTOFILL_SOURCES = {"NTS_BIZ": "국세청 휴·폐업", "KIPRIS": "특허청 특허", "DART": "DART 매출·근로자 수"}


@router.post("/manage/autofill", dependencies=[Depends(public_rate_limit)])
async def autofill(link: dict = Depends(manage_link), rid: str = Depends(request_id)):
    """연결된 공공데이터(국세청·특허청·DART)로 이 회사 정보를 지금 채운다. 출처별 결과와 갱신된 프로필 반환."""
    results = []
    for code, label in AUTOFILL_SOURCES.items():
        r = await collector.run_source(code, organization_id=link["organization_id"], request_id=rid)
        results.append({"source": code, "label": label, "ok": r["status"] == "SUCCEEDED", "error": r["error"],
                        "counts": r["counts"]})
    async with transaction() as conn:
        return {"results": results, "profile": await full_view(conn, link["organization_id"])}


@router.post("/manage/evidence", status_code=201, dependencies=[Depends(public_rate_limit)])
async def upload_evidence(file: UploadFile = File(..., description="확인서·인정서·인증서·신용평가 등급 확인서 (PDF·HWP)"),
                          link: dict = Depends(manage_link), rid: str = Depends(request_id)):
    """증빙을 올리면 종류·번호·날짜·등급을 뽑아 돌려준다. 프로필에는 기업이 확인하고 저장할 때 들어간다."""
    limit = get_settings().upload_max_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"파일이 {get_settings().upload_max_mb}MB 를 넘습니다")
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "빈 파일입니다")
    name = (file.filename or "증빙").strip()[:300]
    p = company_evidence.parse(name, data)
    org_id = link["organization_id"]
    async with transaction(None, f"{rid}|company-link:{link['link_id']}") as conn:
        row = await (await conn.execute(
            """INSERT INTO ax.company_evidence (organization_id, file_name, file_ext, byte_size, content_hash,
                                               text_content, parse_status, parse_note, detected_kind, detected)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (organization_id, content_hash) DO UPDATE SET file_name = EXCLUDED.file_name
               RETURNING id, file_name, parse_status, parse_note, detected_kind, detected, created_at""",
            (org_id, name, name.rsplit(".", 1)[-1].lower() if "." in name else None, len(data),
             hashlib.sha256(data).hexdigest(), p.text, p.status, p.note, p.detected.kind,
             Jsonb(p.detected.values)))).fetchone()
    row["text_excerpt"] = (p.text or "")[:600] or None
    return row


@router.delete("/manage/evidence/{evidence_id}", status_code=204, dependencies=[Depends(public_rate_limit)])
async def delete_evidence(evidence_id: int, link: dict = Depends(manage_link), rid: str = Depends(request_id)):
    async with transaction(None, f"{rid}|company-link:{link['link_id']}") as conn:
        cur = await conn.execute("DELETE FROM ax.company_evidence WHERE id = %s AND organization_id = %s",
                                 (evidence_id, link["organization_id"]))
        if cur.rowcount == 0:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "증빙이 없습니다")
    return Response(status_code=204)
