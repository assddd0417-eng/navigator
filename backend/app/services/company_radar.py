"""기업 역량 레이더 6축 (신용·특허·인증·기술·제품·사업참여), 축마다 0~100.

기업이 입력·업로드한 값만으로 계산한다. 신용등급이 없으면 신용 축은 빈 값(None)이고,
나머지 축은 입력이 없으면 0이다. 비교선은 프로필이 있는 전체 기업의 축별 평균.
"""
from __future__ import annotations

from psycopg import AsyncConnection

AXES = [
    ("CREDIT", "신용"),
    ("PATENT", "특허"),
    ("CERT", "인증"),
    ("TECH", "기술"),
    ("PRODUCT", "제품"),
    ("PARTICIPATION", "사업참여"),
]
AXIS_NOTE = {
    "CREDIT": "가장 최근 신용등급의 서열 (AAA = 100, D = 5)",
    "PATENT": "등록 1건 20점, 출원 1건 10점",
    "CERT": "유효한 인증 1건 25점",
    "TECH": "보유 기술 1건 15점(최대 45) + 최고 TRL 9단계 기준 55점",
    "PRODUCT": "제품 1건 20점, 그중 국방 제품은 20점 더",
    "PARTICIPATION": "지원사업 성공·완료 25, 선정 15, 신청·탈락 5 / R&D 주관 25, 참여 15",
}
SUPPORT_POINTS = {"SUCCESS": 25, "COMPLETED": 25, "SELECTED": 15, "APPLIED": 5, "FAILED": 5}
RND_POINTS = {"LEAD": 25, "PARTICIPANT": 15}
TOP_RANK = 22   # code_credit_grade 의 AAA

_SQL = """
SELECT cp.organization_id AS org,
       (SELECT g.rank FROM ax.company_credit_rating r JOIN ax.code_credit_grade g ON g.grade = r.grade
         WHERE r.organization_id = cp.organization_id
         ORDER BY r.rated_on DESC NULLS LAST, r.id DESC LIMIT 1)                                   AS credit_rank,
       (SELECT count(*) FROM ax.company_patent p
         WHERE p.organization_id = cp.organization_id AND p.status = 'REGISTERED')                  AS pat_reg,
       (SELECT count(*) FROM ax.company_patent p
         WHERE p.organization_id = cp.organization_id AND p.status = 'APPLIED')                     AS pat_app,
       (SELECT count(*) FROM ax.company_certification c
         WHERE c.organization_id = cp.organization_id
           AND (c.expires_on IS NULL OR c.expires_on >= current_date))                              AS certs,
       (SELECT count(*) FROM ax.company_technology t WHERE t.organization_id = cp.organization_id)  AS techs,
       (SELECT max(t.trl) FROM ax.company_technology t WHERE t.organization_id = cp.organization_id) AS max_trl,
       (SELECT count(*) FROM ax.company_product x WHERE x.organization_id = cp.organization_id)     AS products,
       (SELECT count(*) FROM ax.company_product x
         WHERE x.organization_id = cp.organization_id AND x.is_defense)                             AS defense_products,
       (SELECT coalesce(json_agg(s.result), '[]') FROM ax.company_support_history s
         WHERE s.organization_id = cp.organization_id)                                             AS support,
       (SELECT coalesce(json_agg(h.role), '[]') FROM ax.company_rnd_history h
         WHERE h.organization_id = cp.organization_id)                                             AS rnd
  FROM ax.company_profile cp
"""


def _cap(v: float) -> int:
    return int(round(min(100.0, max(0.0, v))))


def scores(row: dict) -> dict[str, int | None]:
    tech = min(45, row["techs"] * 15) + (row["max_trl"] or 0) / 9 * 55
    part = (sum(SUPPORT_POINTS.get(r, 0) for r in row["support"])
            + sum(RND_POINTS.get(r, 0) for r in row["rnd"]))
    return {
        "CREDIT": _cap(row["credit_rank"] / TOP_RANK * 100) if row["credit_rank"] else None,
        "PATENT": _cap(row["pat_reg"] * 20 + row["pat_app"] * 10),
        "CERT": _cap(row["certs"] * 25),
        "TECH": _cap(tech),
        "PRODUCT": _cap(row["products"] * 20 + row["defense_products"] * 20),
        "PARTICIPATION": _cap(part),
    }


async def radar(conn: AsyncConnection, org_id: int) -> dict:
    rows = await (await conn.execute(_SQL)).fetchall()
    by_org = {r["org"]: scores(r) for r in rows}
    mine = by_org.get(org_id) or scores_empty()
    axes = []
    for code, label in AXES:
        vals = [s[code] for s in by_org.values() if s[code] is not None]
        axes.append({
            "code": code, "label": label, "note": AXIS_NOTE[code],
            "value": mine[code],
            "average": round(sum(vals) / len(vals)) if vals else None,
        })
    return {"axes": axes, "company_count": len(by_org)}


def scores_empty() -> dict[str, int | None]:
    return {code: (None if code == "CREDIT" else 0) for code, _ in AXES}
