"""D-STATE 6대 성장준비도 진단.

영역별 점수(0~100)는 배점 산정식으로만 계산하고 LLM 은 쓰지 않는다. 같은 입력이면 같은 결과.
확인되지 않은 변수는 값을 추정하지 않고 '미확보'로 두며 해당 배점은 0 이다.

변수값 우선순위
  - 담당자 입력(STAFF) 이 있으면 그 값
  - 단계형(LEVEL): 회사 정보에서 읽은 값과 기업 보완 답변(SELF) 중 높은 단계
  - 숫자형: 회사 정보 값, 없으면 기업 보완 답변
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

RULE_VERSION = "dstate-2026.11"

AREAS = [
    ("TECH", "기술"),
    ("QUALITY", "품질·인증"),
    ("PRODUCTION", "생산·공급망"),
    ("BUSINESS", "사업화·재무"),
    ("DEFENSE", "방산진입"),
    ("EXPORT", "수출"),
]
AREA_KO = dict(AREAS)

# 영역별 산정식 설명 (화면 표시용)
AREA_FORMULA = {
    "TECH": "기본 22 + TRL×7 + 시제품(개발 중 8 / 보유 16) + R&D 인력비율(최대 10)",
    "QUALITY": "기본 25 + DQMS(준비 35 / 보유 65) + 방산이력(과제 5 / 납품 10)",
    "PRODUCTION": "기본 20 + 직원 수(최대 25) + 매출(최대 25) + 시제품(개발 중 9 / 보유 18)",
    "BUSINESS": "기본 18 + 업력(최대 22) + 매출(최대 28) + R&D 인력비율(최대 20)",
    "DEFENSE": "기본 12 + 방산이력(과제 28 / 납품 48) + 적용 무기체계(후보 15 / 특정 25) + 수요(협의 12 / 확인 25)",
    "EXPORT": "기본 10 + 수출경험(민수 35 / 방산 60) + 목표시장(후보 15 / 특정 28)",
}
BASE = {"TECH": 22, "QUALITY": 25, "PRODUCTION": 20, "BUSINESS": 18, "DEFENSE": 12, "EXPORT": 10}

# 단계형 변수의 순서 (뒤로 갈수록 높음)
LEVELS = {
    "PROTOTYPE": ["NONE", "DEVELOPING", "HAVE"],
    "DQMS": ["NONE", "PREPARING", "HAVE"],
    "DEFENSE_HISTORY": ["NONE", "PROJECT", "DELIVERY"],
    "WEAPON_SYSTEM": ["NONE", "CANDIDATE", "SPECIFIED"],
    "DEMAND": ["NONE", "DISCUSSING", "CONFIRMED"],
    "EXPORT_EXPERIENCE": ["NONE", "CIVIL", "DEFENSE"],
    "TARGET_MARKET": ["NONE", "CANDIDATE", "SPECIFIED"],
}
LEVEL_KO = {
    "NONE": "없음", "DEVELOPING": "개발 중", "HAVE": "보유", "PREPARING": "준비 중", "PROJECT": "과제 수행",
    "DELIVERY": "납품 실적", "CANDIDATE": "후보 있음", "SPECIFIED": "특정됨", "DISCUSSING": "협의 중",
    "CONFIRMED": "확인됨", "CIVIL": "민수 수출", "DEFENSE": "방산 수출",
}

# 구간 배점 비율. 기준표 예시를 따르되 구간 경계는 소관부서 협의 전 잠정값
EMPLOYEE_TIERS = [(100, 1.0), (50, 0.75), (10, 0.5), (1, 0.2)]                       # 명 이상
REVENUE_TIERS = [(10_000_000_000, 1.0), (5_000_000_000, 0.75), (1_000_000_000, 0.5), (1, 0.25)]   # 원 이상
AGE_TIERS = [(10, 1.0), (7, 0.75), (3, 0.5), (0, 0.25)]                              # 년 이상
RND_RATIO_TIERS = [(0.2, 1.0), (0.1, 0.7), (0.05, 0.4), (0.0001, 0.2)]               # 비율 이상

# 상태유형: 위에서부터 먼저 맞는 것
STATE_RULES = [
    ("EXPORT_EXPAND", "수출 확장기업", "수출 ≥ 75, 방산진입 ≥ 70",
     lambda s: s["EXPORT"] >= 75 and s["DEFENSE"] >= 70),
    ("MASS_PRODUCTION", "양산·공급망 고도화기업", "품질·인증 ≥ 65, 생산·공급망 ≥ 70, 방산진입 ≥ 60",
     lambda s: s["QUALITY"] >= 65 and s["PRODUCTION"] >= 70 and s["DEFENSE"] >= 60),
    ("DEFENSE_ENTRY", "방산진입 준비기업", "기술 ≥ 70, 방산진입 < 50",
     lambda s: s["TECH"] >= 70 and s["DEFENSE"] < 50),
    ("TECH_TRANSITION", "기술개발·사업화 전환기업", "기술 ≥ 60, 방산진입 ≥ 45",
     lambda s: s["TECH"] >= 60 and s["DEFENSE"] >= 45),
    ("FOUNDATION", "기초역량 정비기업", "그 외", lambda s: True),
]
STATE_KO = {code: label for code, label, _, _ in STATE_RULES}

# 낮은 영역의 우선 보완과제
AREA_TASK = {
    "TECH": "보유기술 TRL 고도화와 시제품 제작",
    "QUALITY": "DQMS 등 품질보증체계 구축",
    "PRODUCTION": "생산설비·인력 확보와 양산 준비",
    "BUSINESS": "R&D 인력 확충과 사업화 실적 확보",
    "DEFENSE": "적용 무기체계·수요처 확보, 방산 과제 참여 실적 축적",
    "EXPORT": "목표 수출시장 구체화와 해외 인증 준비",
}


@dataclass
class VarValue:
    code: str
    value: Any = None            # 미확보면 None
    source: str | None = None    # PROFILE / CERT / SELF / STAFF
    source_label: str | None = None
    checked_on: str | None = None


@dataclass
class DiagnosisInput:
    name: str
    as_of: date
    values: dict[str, VarValue] = field(default_factory=dict)

    def get(self, code: str) -> Any:
        v = self.values.get(code)
        return v.value if v else None


def _tier(v: float | None, tiers: list[tuple[float, float]]) -> float:
    if v is None:
        return 0.0
    for lo, ratio in tiers:
        if v >= lo:
            return ratio
    return 0.0


def _level(inp: DiagnosisInput, code: str, points: dict[str, int]) -> int:
    return points.get(inp.get(code) or "NONE", 0)


def rnd_ratio(inp: DiagnosisInput) -> float | None:
    staff, emp = inp.get("RND_STAFF"), inp.get("EMPLOYEE_COUNT")
    if staff is None or not emp:
        return None
    return min(1.0, staff / emp)


def business_years(inp: DiagnosisInput) -> float | None:
    opened = inp.get("BUSINESS_AGE")
    if not opened:
        return None
    return (inp.as_of - date.fromisoformat(opened)).days / 365.25


def area_scores(inp: DiagnosisInput) -> dict[str, dict]:
    """영역별 점수와 항목별 배점. 점수는 100 에서 자른다."""
    trl = inp.get("TRL")
    ratio = rnd_ratio(inp)
    emp, rev, years = inp.get("EMPLOYEE_COUNT"), inp.get("REVENUE"), business_years(inp)
    parts: dict[str, list[tuple[str, int]]] = {
        "TECH": [("TRL", (trl or 0) * 7),
                 ("PROTOTYPE", _level(inp, "PROTOTYPE", {"DEVELOPING": 8, "HAVE": 16})),
                 ("RND_STAFF", round(10 * _tier(ratio, RND_RATIO_TIERS)))],
        "QUALITY": [("DQMS", _level(inp, "DQMS", {"PREPARING": 35, "HAVE": 65})),
                    ("DEFENSE_HISTORY", _level(inp, "DEFENSE_HISTORY", {"PROJECT": 5, "DELIVERY": 10}))],
        "PRODUCTION": [("EMPLOYEE_COUNT", round(25 * _tier(emp, EMPLOYEE_TIERS))),
                       ("REVENUE", round(25 * _tier(rev, REVENUE_TIERS))),
                       ("PROTOTYPE", _level(inp, "PROTOTYPE", {"DEVELOPING": 9, "HAVE": 18}))],
        "BUSINESS": [("BUSINESS_AGE", round(22 * _tier(years, AGE_TIERS))),
                     ("REVENUE", round(28 * _tier(rev, REVENUE_TIERS))),
                     ("RND_STAFF", round(20 * _tier(ratio, RND_RATIO_TIERS)))],
        "DEFENSE": [("DEFENSE_HISTORY", _level(inp, "DEFENSE_HISTORY", {"PROJECT": 28, "DELIVERY": 48})),
                    ("WEAPON_SYSTEM", _level(inp, "WEAPON_SYSTEM", {"CANDIDATE": 15, "SPECIFIED": 25})),
                    ("DEMAND", _level(inp, "DEMAND", {"DISCUSSING": 12, "CONFIRMED": 25}))],
        "EXPORT": [("EXPORT_EXPERIENCE", _level(inp, "EXPORT_EXPERIENCE", {"CIVIL": 35, "DEFENSE": 60})),
                   ("TARGET_MARKET", _level(inp, "TARGET_MARKET", {"CANDIDATE": 15, "SPECIFIED": 28}))],
    }
    out = {}
    for code, label in AREAS:
        items = parts[code]
        raw = BASE[code] + sum(p for _, p in items)
        missing = sorted({v for v, _ in items if inp.get(v) is None
                          or (v == "RND_STAFF" and ratio is None)})
        out[code] = {"code": code, "label": label, "score": min(100, raw), "base": BASE[code],
                     "items": [{"variable": v, "points": p} for v, p in items],
                     "missing": missing, "formula": AREA_FORMULA[code]}
    return out


def state_type(scores: dict[str, int]) -> tuple[str, str]:
    for code, label, _, cond in STATE_RULES:
        if cond(scores):
            return code, label
    return "FOUNDATION", STATE_KO["FOUNDATION"]


def _strength_text(code: str, inp: DiagnosisInput) -> str:
    trl, proto = inp.get("TRL"), inp.get("PROTOTYPE")
    if code == "TECH":
        bits = [f"TRL {trl}단계 핵심기술" if trl else "보유 기술", "시제품 보유" if proto == "HAVE" else None]
        return " · ".join(b for b in bits if b)
    if code == "QUALITY":
        return "국방품질경영체제(DQMS) 보유" if inp.get("DQMS") == "HAVE" else "품질체계 준비"
    if code == "PRODUCTION":
        emp = inp.get("EMPLOYEE_COUNT")
        return f"생산 인력 {emp}명 기반" if emp else "생산 기반 보유"
    if code == "BUSINESS":
        years = business_years(inp)
        return f"업력 {int(years)}년, 매출 실적" if years else "매출 실적과 R&D 인력"
    if code == "DEFENSE":
        hist = inp.get("DEFENSE_HISTORY")
        return {"DELIVERY": "군 납품 실적", "PROJECT": "방산 과제 수행 실적"}.get(hist, "방산 수요 확보")
    hist = inp.get("EXPORT_EXPERIENCE")
    return {"DEFENSE": "방산 수출 실적", "CIVIL": "민수 수출 실적"}.get(hist, "수출 준비")


def diagnose(inp: DiagnosisInput) -> dict:
    """진단 결과 (저장 전). 점수·상태유형·강점·우선 보완과제·요약문."""
    areas = area_scores(inp)
    scores = {c: a["score"] for c, a in areas.items()}
    order = [c for c, _ in AREAS]
    ranked = sorted(order, key=lambda c: (-scores[c], order.index(c)))
    weakest = sorted(order, key=lambda c: (scores[c], order.index(c)))[0]
    total = round(sum(scores.values()) / len(scores))
    st_code, st_label = state_type(scores)
    strengths = [{"area": c, "label": AREA_KO[c], "score": scores[c], "text": _strength_text(c, inp)}
                 for c in ranked[:3] if scores[c] >= 50]
    weak_order = sorted(order, key=lambda c: (scores[c], order.index(c)))[:3]
    tasks = [{"area": c, "label": AREA_KO[c], "score": scores[c], "text": AREA_TASK[c]} for c in weak_order]
    missing = sorted({m for a in areas.values() for m in a["missing"]})
    return {
        "rule_version": RULE_VERSION,
        "as_of": inp.as_of.isoformat(),
        "total_score": total,
        "state_type": st_code, "state_label": st_label,
        "weakest_area": weakest, "weakest_label": AREA_KO[weakest],
        "areas": [areas[c] for c in order],
        "strengths": strengths,
        "tasks": tasks,
        "missing": missing,
        "summary": summary_text(inp.name, total, st_label, scores, ranked, weak_order),
    }


def summary_text(name: str, total: int, st_label: str, scores: dict[str, int],
                 ranked: list[str], weak: list[str]) -> str:
    top = ranked[0]
    low1, low2 = weak[0], weak[1]
    s = f"{name}의 종합 준비도는 {total}점으로 {st_label.removesuffix('기업')} 단계에 해당함. "
    if scores[top] >= 50:
        s += f"강점 영역은 {AREA_KO[top]}({scores[top]}점)이고, "
    s += (f"상대적으로 낮은 영역은 {AREA_KO[low1]}({scores[low1]}점), {AREA_KO[low2]}({scores[low2]}점)임. "
          f"우선 보완과제는 {AREA_TASK[low1]}, 다음 보완과제는 {AREA_TASK[low2]}임.")
    return s


# DB

_FACTS_SQL = """
SELECT o.name, cp.opened_on, cp.established_on, cp.employee_count, cp.annual_revenue_krw,
       cp.military_supply_krw, cp.defense_goods, cp.export_krw, cp.updated_at::date AS profile_on,
       (SELECT max(t.trl) FROM ax.company_technology t WHERE t.organization_id = o.id) AS max_trl,
       (SELECT max(c.issued_on) FROM ax.company_certification c
         WHERE c.organization_id = o.id AND c.cert_type_code = 'DEFENSE_QMS'
           AND (c.expires_on IS NULL OR c.expires_on >= %(as_of)s)) AS dqms_on,
       (SELECT count(*) FROM ax.company_certification c
         WHERE c.organization_id = o.id AND c.cert_type_code = 'DEFENSE_QMS'
           AND (c.expires_on IS NULL OR c.expires_on >= %(as_of)s)) AS dqms_count
  FROM ax.organization o JOIN ax.company_profile cp ON cp.organization_id = o.id
 WHERE o.id = %(org)s
"""


async def variables(conn: AsyncConnection) -> list[dict]:
    return await (await conn.execute(
        "SELECT code, name_ko, definition, value_type, options, areas, source_desc, question "
        "FROM ax.dstate_variable ORDER BY sort_order")).fetchall()


async def variable_admin(conn: AsyncConnection) -> list[dict]:
    return await (await conn.execute(
        """SELECT v.code, v.name_ko, v.definition, v.value_type, v.options, v.areas, v.source_desc, v.question,
                  v.sort_order, v.updated_at, u.name AS updated_by_name
             FROM ax.dstate_variable v LEFT JOIN ax.app_user u ON u.id = v.updated_by
            ORDER BY v.sort_order""")).fetchall()


async def update_variable(conn: AsyncConnection, code: str, data: dict, user_id: int) -> dict:
    """변수명·정의·증빙 원천·보완 질문·선택지 이름만 고친다. 코드·값 유형·영역·산정식은 바꾸지 않는다."""
    cur = await (await conn.execute("SELECT * FROM ax.dstate_variable WHERE code = %s", (code,))).fetchone()
    if cur is None:
        raise LookupError(code)
    options = cur["options"]
    if data.get("option_labels"):
        known = {o["code"] for o in options}
        if bad := sorted(set(data["option_labels"]) - known):
            raise ValueError(f"없는 선택지: {', '.join(bad)}")
        options = [{**o, "label": data["option_labels"].get(o["code"]) or o["label"]} for o in options]
    if cur["value_type"] == "PROFILE" and data.get("question"):
        raise ValueError("회사 정보에서 읽는 변수에는 보완 질문을 두지 않습니다")
    await conn.execute(
        """UPDATE ax.dstate_variable SET name_ko = %s, definition = %s, source_desc = %s, question = %s,
                  options = %s, updated_at = now(), updated_by = %s WHERE code = %s""",
        (data.get("name_ko") or cur["name_ko"], data.get("definition") or cur["definition"],
         data.get("source_desc") or cur["source_desc"],
         (data["question"] or None) if "question" in data and cur["value_type"] != "PROFILE" else cur["question"],
         Jsonb(options), user_id, code))
    return next(v for v in await variable_admin(conn) if v["code"] == code)


async def _preferred_numbers(conn: AsyncConnection, org_id: int) -> dict[str, Any]:
    rows = await (await conn.execute(
        """SELECT field_name, preferred_value, any_verified FROM ax.v_company_field_compare
            WHERE organization_id = %s AND field_name IN ('employee_count', 'annual_revenue_krw')""",
        (org_id,))).fetchall()
    return {r["field_name"]: r for r in rows if r["preferred_value"] is not None}


async def load_input(conn: AsyncConnection, org_id: int, as_of: date | None = None) -> DiagnosisInput | None:
    as_of = as_of or date.today()
    f = await (await conn.execute(_FACTS_SQL, {"org": org_id, "as_of": as_of})).fetchone()
    if f is None:
        return None
    inp = DiagnosisInput(name=f["name"], as_of=as_of)
    profile_on = f["profile_on"].isoformat()

    derived: dict[str, VarValue] = {}
    if f["max_trl"]:
        derived["TRL"] = VarValue("TRL", int(f["max_trl"]), "PROFILE", "보유 기술", profile_on)
    pref = await _preferred_numbers(conn, org_id)
    emp = pref.get("employee_count")
    if emp:
        derived["EMPLOYEE_COUNT"] = VarValue("EMPLOYEE_COUNT", int(emp["preferred_value"]), "PROFILE",
                                             "외부 확인" if emp["any_verified"] else "회사 정보", profile_on)
    elif f["employee_count"] is not None:
        derived["EMPLOYEE_COUNT"] = VarValue("EMPLOYEE_COUNT", f["employee_count"], "PROFILE", "회사 정보", profile_on)
    rev = pref.get("annual_revenue_krw")
    if rev:
        derived["REVENUE"] = VarValue("REVENUE", int(rev["preferred_value"]), "PROFILE",
                                      "외부 확인" if rev["any_verified"] else "회사 정보", profile_on)
    elif f["annual_revenue_krw"] is not None:
        derived["REVENUE"] = VarValue("REVENUE", f["annual_revenue_krw"], "PROFILE", "회사 정보", profile_on)
    opened = f["opened_on"] or f["established_on"]
    if opened:
        derived["BUSINESS_AGE"] = VarValue("BUSINESS_AGE", opened.isoformat(), "PROFILE", "회사 정보(개업일)",
                                           profile_on)
    if f["dqms_count"]:
        derived["DQMS"] = VarValue("DQMS", "HAVE", "CERT", "인증 목록",
                                   f["dqms_on"].isoformat() if f["dqms_on"] else profile_on)
    if (f["military_supply_krw"] or 0) > 0 or f["defense_goods"]:
        derived["DEFENSE_HISTORY"] = VarValue("DEFENSE_HISTORY", "DELIVERY", "PROFILE", "회사 정보(군 납품)",
                                              profile_on)
    if (f["export_krw"] or 0) > 0:
        derived["EXPORT_EXPERIENCE"] = VarValue("EXPORT_EXPERIENCE", "CIVIL", "PROFILE", "회사 정보(수출 실적)",
                                                profile_on)

    answers: dict[str, dict[str, dict]] = {}
    for r in await (await conn.execute(
            "SELECT variable_code, origin, value, updated_at FROM ax.company_dstate_value WHERE organization_id = %s",
            (org_id,))).fetchall():
        answers.setdefault(r["variable_code"], {})[r["origin"]] = r

    for code in [*LEVELS, "TRL", "RND_STAFF", "EMPLOYEE_COUNT", "REVENUE", "BUSINESS_AGE"]:
        got = answers.get(code, {})
        staff, own, d = got.get("STAFF"), got.get("SELF"), derived.get(code)
        if staff is not None:
            inp.values[code] = VarValue(code, staff["value"], "STAFF", "담당자 확인",
                                        staff["updated_at"].date().isoformat())
        elif code in LEVELS and d and own:
            order = LEVELS[code]
            pick_own = order.index(own["value"]) > order.index(d.value) if own["value"] in order else False
            inp.values[code] = (VarValue(code, own["value"], "SELF", "기업 답변", own["updated_at"].date().isoformat())
                                if pick_own else d)
        elif d:
            inp.values[code] = d
        elif own is not None:
            inp.values[code] = VarValue(code, own["value"], "SELF", "기업 답변", own["updated_at"].date().isoformat())
        else:
            inp.values[code] = VarValue(code)
    return inp


def display_value(code: str, value: Any) -> str | None:
    if value is None:
        return None
    if code in LEVELS:
        return LEVEL_KO.get(value, str(value))
    if code == "TRL":
        return f"{value}단계"
    if code in ("RND_STAFF", "EMPLOYEE_COUNT"):
        return f"{value:,}명"
    if code == "REVENUE":
        return f"{value / 100_000_000:,.1f}억 원"
    if code == "BUSINESS_AGE":
        return f"개업 {value}"
    return str(value)


def variable_rows(defs: list[dict], inp: DiagnosisInput) -> list[dict]:
    """변수별 값·출처·확인일 (미확보 포함)."""
    rows = []
    for d in defs:
        v = inp.values.get(d["code"]) or VarValue(d["code"])
        rows.append({
            "code": d["code"], "name": d["name_ko"], "definition": d["definition"],
            "value_type": d["value_type"], "options": d["options"], "areas": d["areas"],
            "areas_label": [AREA_KO[a] for a in d["areas"]], "source_desc": d["source_desc"],
            "question": d["question"],
            "value": v.value, "display": display_value(d["code"], v.value),
            "source": v.source, "source_label": v.source_label, "checked_on": v.checked_on,
            "missing": v.value is None,
        })
    return rows


def validate_value(defn: dict, value: Any) -> Any:
    """보완 답변 형식 확인. 틀리면 ValueError."""
    code, vt = defn["code"], defn["value_type"]
    if vt == "PROFILE":
        raise ValueError(f"{defn['name_ko']}은(는) 회사 정보에서 고칩니다")
    if vt == "LEVEL":
        allowed = [o["code"] for o in defn["options"]]
        if value not in allowed:
            raise ValueError(f"{defn['name_ko']}: {', '.join(allowed)} 중 하나")
        return value
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{defn['name_ko']}: 정수")
    if code == "TRL" and not 1 <= value <= 9:
        raise ValueError("TRL 은 1~9")
    if value < 0:
        raise ValueError(f"{defn['name_ko']}: 0 이상")
    return value


async def save_values(conn: AsyncConnection, org_id: int, values: dict[str, Any], origin: str,
                      user_id: int | None = None) -> None:
    """values 의 None 은 그 출처 값을 지운다."""
    defs = {d["code"]: d for d in await variables(conn)}
    for code, value in values.items():
        if code not in defs:
            raise ValueError(f"없는 진단 변수: {code}")
        if value is None:
            await conn.execute("DELETE FROM ax.company_dstate_value WHERE organization_id = %s "
                               "AND variable_code = %s AND origin = %s", (org_id, code, origin))
            continue
        v = validate_value(defs[code], value)
        await conn.execute(
            """INSERT INTO ax.company_dstate_value (organization_id, variable_code, origin, value, updated_by)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (organization_id, variable_code, origin)
               DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, updated_at = now()""",
            (org_id, code, origin, Jsonb(v), user_id))


async def run(conn: AsyncConnection, org_id: int, *, save: bool, user_id: int | None = None) -> dict | None:
    inp = await load_input(conn, org_id)
    if inp is None:
        return None
    defs = await variables(conn)
    result = diagnose(inp)
    result["variables"] = variable_rows(defs, inp)
    result["organization_id"] = org_id
    result["company_name"] = inp.name
    result["diagnosis_id"] = None
    if save:
        snap = {c: {"value": v.value, "source": v.source} for c, v in inp.values.items()}
        row = await (await conn.execute(
            """INSERT INTO ax.company_diagnosis (organization_id, rule_version, total_score, state_type, weakest_area,
                                                 scores, inputs, missing, summary, created_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id, created_at""",
            (org_id, RULE_VERSION, result["total_score"], result["state_type"], result["weakest_area"],
             Jsonb({a["code"]: a["score"] for a in result["areas"]}), Jsonb(snap), result["missing"],
             result["summary"], user_id))).fetchone()
        result["diagnosis_id"] = row["id"]
        result["created_at"] = row["created_at"].isoformat()
    result["previous"] = await previous(conn, org_id, before_id=result["diagnosis_id"])
    return result


async def previous(conn: AsyncConnection, org_id: int, before_id: int | None) -> dict | None:
    """직전 진단 (재상담 비교용)."""
    row = await (await conn.execute(
        """SELECT id, total_score, state_type, scores, created_at FROM ax.company_diagnosis
            WHERE organization_id = %s AND (%s::bigint IS NULL OR id < %s)
            ORDER BY id DESC LIMIT 1""", (org_id, before_id, before_id))).fetchone()
    if row is None:
        return None
    return {"diagnosis_id": row["id"], "total_score": row["total_score"], "state_type": row["state_type"],
            "state_label": STATE_KO.get(row["state_type"], row["state_type"]), "scores": row["scores"],
            "created_at": row["created_at"].isoformat()}


async def history(conn: AsyncConnection, org_id: int) -> list[dict]:
    rows = await (await conn.execute(
        """SELECT d.id, d.total_score, d.state_type, d.weakest_area, d.scores, d.missing, d.created_at,
                  u.name AS created_by_name
             FROM ax.company_diagnosis d LEFT JOIN ax.app_user u ON u.id = d.created_by
            WHERE d.organization_id = %s ORDER BY d.id DESC""", (org_id,))).fetchall()
    return [{**r, "state_label": STATE_KO.get(r["state_type"], r["state_type"]),
             "weakest_label": AREA_KO.get(r["weakest_area"]), "created_at": r["created_at"].isoformat()}
            for r in rows]
