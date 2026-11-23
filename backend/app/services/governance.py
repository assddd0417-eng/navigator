"""성장경로 서비스 정의, 주체별 역할(RACI), AI 자율성 등급, 기업정보 열람 권한.

서비스 안내 화면과 각 결과 화면의 확정 관문 표시에 쓴다. 표는 운영 제안 기준이며
자격요건 판단기준은 지원사업 공고·운영규정을 따른다.
"""
from __future__ import annotations

from psycopg import AsyncConnection

from app.auth import CurrentUser

ROLES = {"STAFF": "기업지원 담당자", "PROGRAM_OWNER": "지원사업 소관부서", "AX_ADMIN": "AX 주관부서"}
CONSULT = ("STAFF",)
CRITERIA = ("PROGRAM_OWNER", "AX_ADMIN")
CRITERIA_READ = ("STAFF", "PROGRAM_OWNER", "AX_ADMIN")
ANNOUNCE = ("STAFF", "PROGRAM_OWNER")
AUDIT = ("AX_ADMIN", "STAFF")

LEVELS = [
    {"code": "L1", "label": "조력", "desc": "기업정보 확인·진단·자격 판단·근거 제시까지만 수행. 확정과 기업 안내는 담당자가 판단"},
    {"code": "L2", "label": "수동승인", "desc": "경로 추천·상담결과서 초안 생성. 담당자 확인·확정 후에만 안내"},
    {"code": "L3", "label": "조건부자율", "desc": "판단기준 구성·반영, 상담이력 기록 등 확정된 기준 안에서만 처리. 자격 판정·사업 선정에는 적용 안 함"},
]

# 기능별 확정 관문: 결과 화면에 표시
GATES = {
    "dstate": {"level": "L1", "gate": "진단 확인 관문", "owner": "기업지원 담당자",
               "text": "진단 결과는 상담 참고자료입니다. 진단 확정과 기업 안내 여부는 담당자가 판단합니다."},
    "eligibility": {"level": "L1", "gate": "자격 확정 관문", "owner": "기업지원 담당자",
                    "text": "최종 자격 판정은 담당자가 확정합니다. 근거를 인용하지 못한 판단은 결과로 내지 않습니다."},
    "route": {"level": "L2", "gate": "추천결과 확정 관문", "owner": "기업지원 담당자",
              "text": "추천결과와 상담결과서는 초안입니다. 담당자가 확정한 내용만 기업에 안내합니다."},
    "criteria": {"level": "L3", "gate": "판단기준 반영", "owner": "지원사업 소관부서",
                 "text": "공고 요건 해석과 판단기준 구성은 자동으로 하고, 점검항목 밖 요건은 소관부서가 보정합니다."},
    "history": {"level": "L3", "gate": "상담이력 기록", "owner": "AX 주관부서",
                "text": "상담이력은 자동으로 남기고, AX 주관부서가 정기 점검해 기준을 보정합니다."},
}

RACI = [
    {"area": "자격요건 판단기준 관리", "task": "공고 요건 해석·판단기준 구성", "company": "-", "staff": "I",
     "owner": "R/A (공고 등록·예외 요건 보정)", "ax": "-", "agent": "R (요건 해석·판단기준 구성)", "level": "L3"},
    {"area": "자격요건 판단기준 관리", "task": "판단기준 반영", "company": "-", "staff": "I", "owner": "I",
     "ax": "C (시스템 반영)", "agent": "R (판단기준 자동 반영)", "level": "L3"},
    {"area": "기업 상담", "task": "기업정보 확인·보완", "company": "R (보완자료 제출)", "staff": "R/A (보완 필요 판단)",
     "owner": "-", "ax": "-", "agent": "R (기업 확인·보완 요청)", "level": "L1"},
    {"area": "기업 상담", "task": "성장준비도 진단", "company": "I", "staff": "A (진단 결과 확정)", "owner": "-",
     "ax": "-", "agent": "R (6대 준비도 점수 산출)", "level": "L1"},
    {"area": "기업 상담", "task": "AI 자격 판단", "company": "-", "staff": "A (판정 결과 확정)", "owner": "-",
     "ax": "-", "agent": "R (요건 대조·근거 인용)", "level": "L1"},
    {"area": "공통 운영", "task": "경로 추천·결과서 초안", "company": "-", "staff": "A (추천 검토·확정)", "owner": "-",
     "ax": "-", "agent": "R (진단·이력 기반 경로·결과서 초안)", "level": "L2"},
    {"area": "공통 운영", "task": "결과 확정·안내", "company": "I (안내 수신)", "staff": "R/A (결과 확정·안내)",
     "owner": "I", "ax": "-", "agent": "-", "level": "-"},
    {"area": "공통 운영", "task": "상담이력 기록·점검", "company": "-", "staff": "I", "owner": "I",
     "ax": "A (이력 점검·기준 보정)", "agent": "R (상담이력 기록)", "level": "L3"},
]

SERVICE = {
    "name": "AI 기반 방산기업 성장경로 서비스",
    "summary": "방산기업의 보유기술·사업이력·지원현황 등 기업정보와 지원사업 공고·지침을 종합 분석해 기업별 성장준비도 "
               "진단과 자격요건 검토를 지원하고, 맞춤형 지원사업과 단계별 성장경로를 안내한다.",
    "targets": ["기업지원 상담 담당자", "지원사업 소관부서"],
    "functions": [
        {"code": "A", "name": "성장역량 진단 (D-STATE)",
         "items": ["기업정보 연계 조회와 미확보 정보 보완", "6대 성장준비도 점수와 강점·부족역량 도출"]},
        {"code": "B", "name": "지원사업 자격검토",
         "items": ["공고·지침의 신청·제외요건 추출과 판단기준 구성", "기업정보 대조로 충족·미충족·확인 필요 판정과 적합도"]},
        {"code": "C", "name": "맞춤형 성장경로 추천 (D-ROUTE)",
         "items": ["적합 지원사업 추천과 추천·미추천 사유", "현재·다음·중장기 성장경로와 준비사항 안내"]},
    ],
    "goals": ["기업 성장역량 진단 체계화", "지원사업 자격검토 부담 경감", "맞춤형 후속사업 연계 강화"],
    "flow": [
        "담당자가 기업과 검토업무를 고르고, 필요하면 보완자료를 첨부한다",
        "열람 권한을 확인하고 기업 등록 여부와 미확보 변수를 확인한다",
        "기업정보를 조회해 6대 성장준비도를 산출한다 (AI 사용 안 함)",
        "판단기준과 공고 조항을 검색해 근거로 쓴다",
        "근거를 인용해 자격을 판단하고, 수치 요건은 계산으로 다시 확인한다",
        "종합을 고르면 성장경로를 구성하고 상담결과서 초안을 만든다",
        "결과를 보여 주고 담당자 피드백을 받는다",
        "결과와 피드백을 상담이력으로 남긴다",
    ],
    "integrations": [
        {"name": "DISIS 기업·품목정보", "status": "연동 예정"},
        {"name": "PMS·DTiMS 과제수행·지원이력", "status": "연동 예정"},
        {"name": "국세청 휴폐업", "status": "연동 (사업자 상태 조회)"},
        {"name": "조달청 부정당제재", "status": "연동 예정 (지금은 기업·담당자 입력)"},
        {"name": "SSO 로그인", "status": "연동 예정 (지금은 담당자 선택)"},
    ],
}


def info() -> dict:
    return {"service": SERVICE, "roles": [{"code": c, "label": l} for c, l in ROLES.items()],
            "levels": LEVELS, "gates": GATES, "raci": RACI}


# ---------- 기업정보 열람 권한 ----------

def _all_access(user: CurrentUser) -> bool:
    return "AX_ADMIN" in user.roles or "ADMIN" in user.roles


ACCESS_SQL = """(NOT EXISTS (SELECT 1 FROM ax.company_access ca WHERE ca.organization_id = {org})
                 OR EXISTS (SELECT 1 FROM ax.company_access ca
                             WHERE ca.organization_id = {org} AND ca.department_id = %(dept)s))"""


def access_filter(user: CurrentUser, org_col: str = "o.id") -> tuple[str, dict]:
    """조회 SQL 에 붙일 열람 권한 조건."""
    if _all_access(user):
        return "TRUE", {}
    return ACCESS_SQL.format(org=org_col), {"dept": user.department_id or 0}


async def can_view(conn: AsyncConnection, user: CurrentUser, org_id: int) -> bool:
    if _all_access(user):
        return True
    cond, params = access_filter(user, "%(org)s")
    row = await (await conn.execute(f"SELECT {cond} AS ok", {**params, "org": org_id})).fetchone()
    return bool(row["ok"])


async def get_access(conn: AsyncConnection, org_id: int) -> dict:
    rows = await (await conn.execute(
        """SELECT d.id, d.name, (ca.organization_id IS NOT NULL) AS allowed
             FROM ax.department d LEFT JOIN ax.company_access ca
                  ON ca.department_id = d.id AND ca.organization_id = %s
            ORDER BY d.id""", (org_id,))).fetchall()
    restricted = any(r["allowed"] for r in rows)
    return {"organization_id": org_id, "restricted": restricted,
            "departments": rows,
            "text": "지정한 부서와 AX 주관부서만 볼 수 있음" if restricted else "모든 담당 부서가 볼 수 있음"}


async def set_access(conn: AsyncConnection, org_id: int, department_ids: list[int], user_id: int) -> dict:
    ids = sorted(set(department_ids))
    if ids:
        found = {r["id"] for r in await (await conn.execute(
            "SELECT id FROM ax.department WHERE id = ANY(%s)", (ids,))).fetchall()}
        if missing := [i for i in ids if i not in found]:
            raise ValueError(f"없는 부서: {missing}")
    await conn.execute("DELETE FROM ax.company_access WHERE organization_id = %s AND NOT (department_id = ANY(%s))",
                       (org_id, ids))
    for d in ids:
        await conn.execute(
            """INSERT INTO ax.company_access (organization_id, department_id, created_by) VALUES (%s, %s, %s)
               ON CONFLICT DO NOTHING""", (org_id, d, user_id))
    return await get_access(conn, org_id)
