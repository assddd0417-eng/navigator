"""기업 프로필 저장·조회. public_view 는 사업자번호만으로 보는 범위(신용·매출 제외), full_view 는 관리 링크용."""
from datetime import date, datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.services import company_radar
from app.repositories.sql import insert
from app.services.bizno import format_bizno

VERIFY_LABEL = {"VERIFIED": "확인됨", "UNVERIFIED": "미확인", "FAILED": "불일치"}
BUSINESS_STATUS_LABEL = {"ACTIVE": "계속사업자", "SUSPENDED": "휴업", "CLOSED": "폐업", "UNKNOWN": "모름"}

PROFILE_FIELDS = ("main_business", "homepage", "company_size", "established_on", "employee_count",
                  "annual_revenue_krw", "revenue_year", "region", "address",
                  "tax_delinquent", "insolvent", "rnd_restricted", "procurement_sanctioned", "defense_goods", "military_supply_krw",
                  "export_krw", "export_year")

LIST_TABLES = {
    "patents": "company_patent",
    "certifications": "company_certification",
    "credit_ratings": "company_credit_rating",
    "rnd_history": "company_rnd_history",
    "products": "company_product",
    "technologies": "company_technology",
    "support_history": "company_support_history",
}


def _json_value(v: Any) -> Any:
    return v.isoformat() if isinstance(v, (date, datetime)) else v


async def record_field(conn: AsyncConnection, org_id: int, field_name: str, value: Any, source_kind: str, *,
                       source_code: str | None = None, raw_record_id: int | None = None,
                       verified: bool = False) -> None:
    await conn.execute(
        """INSERT INTO ax.company_field_source
                  (organization_id, field_name, value, source_kind, external_source_id, raw_record_id,
                   is_verified, verified_at)
           VALUES (%(org)s, %(f)s, %(v)s, %(k)s,
                   (SELECT id FROM ax.external_source WHERE code = %(src)s), %(raw)s,
                   %(ver)s, CASE WHEN %(ver)s THEN now() END)
           ON CONFLICT (organization_id, field_name, source_kind, COALESCE(external_source_id, 0))
           DO UPDATE SET value = EXCLUDED.value, raw_record_id = EXCLUDED.raw_record_id,
                         is_verified = EXCLUDED.is_verified, verified_at = EXCLUDED.verified_at,
                         verified_by = NULL, recorded_at = now()""",
        {"org": org_id, "f": field_name, "v": Jsonb(_json_value(value)), "k": source_kind,
         "src": source_code, "raw": raw_record_id, "ver": verified})


async def insert_list_items(conn: AsyncConnection, org_id: int, key: str, items: list, origin: str = "SELF") -> None:
    for item in items:
        data = {**item.model_dump(), "organization_id": org_id, "origin": origin}
        if data.get("company_evidence_id") and not await (await conn.execute(
                "SELECT 1 FROM ax.company_evidence WHERE id = %s AND organization_id = %s",
                (data["company_evidence_id"], org_id))).fetchone():
            data["company_evidence_id"] = None   # 다른 회사 증빙은 연결하지 않는다
        await insert(conn, LIST_TABLES[key], data)


async def replace_self_items(conn: AsyncConnection, org_id: int, key: str, items: list) -> None:
    # SELF 행만 교체
    await conn.execute(
        f"DELETE FROM ax.{LIST_TABLES[key]} WHERE organization_id = %s AND origin = 'SELF'", (org_id,))
    await insert_list_items(conn, org_id, key, items)


async def find_by_bizno(conn: AsyncConnection, bizno: str, *, lock: bool = False) -> dict | None:
    return await (await conn.execute(
        """SELECT o.id AS organization_id, o.name, o.org_type, cp.organization_id IS NOT NULL AS has_profile,
                  cp.registered_email, cp.biz_verify_status, cp.business_status
             FROM ax.organization o
             LEFT JOIN ax.company_profile cp ON cp.organization_id = o.id
            WHERE o.business_reg_no = %s""" + (" FOR UPDATE OF o" if lock else ""),
        (bizno,))).fetchone()


async def _patents(conn: AsyncConnection, org_id: int) -> list[dict]:
    return await (await conn.execute(
        """SELECT id, application_no, registration_no, title, abstract, ipc_codes, status, applied_on, registered_on,
                  origin, verified_at IS NOT NULL AS is_verified
             FROM ax.company_patent WHERE organization_id = %s
            ORDER BY registered_on DESC NULLS LAST, applied_on DESC NULLS LAST, id""", (org_id,))).fetchall()


async def public_view(conn: AsyncConnection, org_id: int) -> dict:
    p = await (await conn.execute(
        """SELECT o.business_reg_no, o.name AS company_name, cp.biz_verify_status, cp.business_status
             FROM ax.organization o JOIN ax.company_profile cp ON cp.organization_id = o.id
            WHERE o.id = %s""", (org_id,))).fetchone()
    patents = await _patents(conn, org_id)
    return {
        "visibility": "PUBLIC",
        "business_reg_no": format_bizno(p["business_reg_no"]),
        "company_name": p["company_name"],
        "biz_verify_status": p["biz_verify_status"],
        "biz_verify_label": VERIFY_LABEL[p["biz_verify_status"]],
        "business_status": p["business_status"],
        "business_status_label": BUSINESS_STATUS_LABEL[p["business_status"]],
        "patents": [{k: v for k, v in pt.items() if k not in ("id", "abstract", "origin")} for pt in patents],
        "note": "신용등급·매출·자가입력 내용은 '회사 정보 입력·수정'에서만 볼 수 있습니다",
    }


async def full_view(conn: AsyncConnection, org_id: int) -> dict:
    p = await (await conn.execute(
        f"""SELECT o.id AS organization_id, o.business_reg_no, o.name AS company_name,
                   cp.representative_name, cp.opened_on, cp.is_defense_company,
                   {", ".join(f"cp.{f}" for f in PROFILE_FIELDS)},
                   cp.business_status, cp.business_status_checked_at, cp.biz_verify_status, cp.biz_verified_at,
                   cp.registered_email, cp.registration_channel, cp.created_at, cp.updated_at,
                   cp.outreach_consent_at
              FROM ax.organization o JOIN ax.company_profile cp ON cp.organization_id = o.id
             WHERE o.id = %s""", (org_id,))).fetchone()
    p["business_reg_no"] = format_bizno(p["business_reg_no"])
    p["biz_verify_label"] = VERIFY_LABEL[p["biz_verify_status"]]
    p["business_status_label"] = BUSINESS_STATUS_LABEL[p["business_status"]]
    p["visibility"] = "OWNER"
    p["patents"] = await _patents(conn, org_id)
    p["certifications"] = await (await conn.execute(
        """SELECT c.id, c.cert_type_code, t.name_ko AS cert_type_name, c.cert_no, c.issuer, c.issued_on, c.expires_on,
                  c.expires_on IS NOT NULL AND c.expires_on < current_date AS is_expired,
                  c.evidence_document_id, c.company_evidence_id, c.origin, c.verified_at IS NOT NULL AS is_verified
             FROM ax.company_certification c JOIN ax.code_certification_type t ON t.code = c.cert_type_code
            WHERE c.organization_id = %s ORDER BY t.sort_order, c.id""", (org_id,))).fetchall()
    p["credit_ratings"] = await (await conn.execute(
        """SELECT id, agency, grade, rated_on, valid_until, evidence_document_id, company_evidence_id, origin,
                  verified_at IS NOT NULL AS is_verified
             FROM ax.company_credit_rating WHERE organization_id = %s
            ORDER BY rated_on DESC NULLS LAST, id""", (org_id,))).fetchall()
    p["rnd_history"] = await (await conn.execute(
        """SELECT h.id, h.project_no, h.title, h.funding_agency, h.start_date, h.end_date, h.amount_krw, h.role,
                  h.summary, h.origin, h.verified_at IS NOT NULL AS is_verified
             FROM ax.company_rnd_history h
            WHERE h.organization_id = %s ORDER BY h.start_date DESC NULLS LAST, h.id""", (org_id,))).fetchall()
    p["products"] = await (await conn.execute(
        """SELECT id, name, category, description, is_defense, customers, origin
             FROM ax.company_product WHERE organization_id = %s ORDER BY id""", (org_id,))).fetchall()
    p["technologies"] = await (await conn.execute(
        """SELECT id, tech_name, description, trl, origin
             FROM ax.company_technology WHERE organization_id = %s ORDER BY id""", (org_id,))).fetchall()
    p["support_history"] = await (await conn.execute(
        """SELECT id, program_name, agency, year, result, amount_krw, announcement_id, summary, origin
             FROM ax.company_support_history WHERE organization_id = %s
            ORDER BY year DESC NULLS LAST, id""", (org_id,))).fetchall()
    p["evidence"] = await (await conn.execute(
        """SELECT id, file_name, parse_status, parse_note, detected_kind, detected, created_at
             FROM ax.company_evidence WHERE organization_id = %s ORDER BY id DESC""", (org_id,))).fetchall()
    p["field_sources"] = await (await conn.execute(
        """SELECT field_name, preferred_value, any_verified, differs, sources
             FROM ax.v_company_field_compare WHERE organization_id = %s ORDER BY field_name""", (org_id,))).fetchall()
    p["radar"] = await company_radar.radar(conn, org_id)
    return p
