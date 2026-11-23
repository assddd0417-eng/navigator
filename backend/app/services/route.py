"""맞춤형 성장경로 (D-ROUTE). D-STATE 진단, 공고별 자격검토, 유사 기업 지원 이력을 합쳐 단기·중기·장기 경로를 만든다.

  현재 단계   상태유형으로 정한다 (기초역량 정비·방산진입 준비 = 방산진입, 기술개발·사업화 전환 = 기술개발,
              양산·공급망 고도화·수출 확장 = 양산·수출). 경로는 현재 단계부터 마지막 단계까지.
  추천 사업   program_route 의 단계별 사업. 근거 공고가 없는 사업은 추천하지 않는다.
  준비상태    단기 단계에서 접수중·접수전 공고가 있고 신청 가능 + 진입조건 충족이면 '즉시 신청',
              확인 필요이거나 진입조건 미달이면 '보완 후 신청'. 그 밖(중장기, 공고 없음)은 '진입조건 준비'.
              신청 불가·이미 수혜(반복 불가)는 미추천으로 사유와 함께 보여 준다.
  유사 기업   D-STATE 6개 점수가 가까운 기업(최대 12곳)의 지원사업 이력으로 참여 비율·평균 간격을 근거로 단다.
경로와 요약은 템플릿 문장이다. 추천은 선정·지원을 보장하지 않는다.
"""
from __future__ import annotations

import math
from collections import defaultdict

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.services import dstate, eligibility_review
from app.services.eligibility import SUPPORT_DONE, _norm

STATE_STAGE = {"FOUNDATION": "ENTRY", "DEFENSE_ENTRY": "ENTRY", "TECH_TRANSITION": "TECH_DEV",
               "MASS_PRODUCTION": "SCALE", "EXPORT_EXPAND": "SCALE"}
HORIZONS = ["단기 · 1~2년", "중기 · 2~5년", "장기 · 5년 이후"]
READY_KO = {"IMMEDIATE": "즉시 신청", "AFTER_FIX": "보완 후 신청", "PREPARE": "진입조건 준비"}
READY_ORDER = {"IMMEDIATE": 0, "AFTER_FIX": 1, "PREPARE": 2}
PER_STAGE = 2
SIMILAR_K = 12
NOTICE = "추천 경로는 상담 참고자료이며 사업 선정·지원을 보장하지 않습니다."


async def stages(conn: AsyncConnection) -> list[dict]:
    return await (await conn.execute(
        "SELECT code, name_ko, goal, areas FROM ax.growth_stage ORDER BY sort_order")).fetchall()


async def route_programs(conn: AsyncConnection) -> list[dict]:
    return await (await conn.execute(
        """SELECT p.id, p.program_code, p.name, p.purpose, r.stage_code, r.next_program_ids, r.entry_condition,
                  r.entry_min_scores, r.prep_tasks, r.expected_output, r.repeatable, r.sort_order, r.updated_at
             FROM ax.program_route r JOIN ax.program p ON p.id = r.program_id
            WHERE p.is_active ORDER BY r.stage_code, r.sort_order, p.id""")).fetchall()


async def _announcements_by_program(conn: AsyncConnection, program_ids: list[int]) -> dict[int, dict]:
    """사업별 지금 공고(접수중·접수전)와 가장 최근 공고."""
    rows = await (await conn.execute(
        """SELECT id, program_id, title, receipt_state, receipt_end FROM ax.v_announcement
            WHERE status = 'PUBLISHED' AND program_id = ANY(%s)
            ORDER BY receipt_end DESC NULLS LAST, id DESC""", (program_ids,))).fetchall()
    out: dict[int, dict] = defaultdict(lambda: {"current": [], "latest": None})
    for r in rows:
        p = out[r["program_id"]]
        if r["receipt_state"] in ("OPEN", "UPCOMING"):
            p["current"].append(r)
        if p["latest"] is None:
            p["latest"] = r
    return out


async def _support(conn: AsyncConnection, org_ids: list[int] | None = None) -> dict[int, list[dict]]:
    rows = await (await conn.execute(
        """SELECT s.organization_id, s.program_name, s.year, s.result, a.program_id
             FROM ax.company_support_history s LEFT JOIN ax.announcement a ON a.id = s.announcement_id
            WHERE (%(ids)s::bigint[] IS NULL OR s.organization_id = ANY(%(ids)s))
              AND s.result = ANY(%(done)s)""", {"ids": org_ids, "done": list(SUPPORT_DONE)})).fetchall()
    out: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        out[r["organization_id"]].append(r)
    return out


def took_program(history: list[dict], program: dict) -> dict | None:
    """지원 이력 중 이 사업에 해당하는 것 (공고로 연결됐거나 이름이 같음)."""
    name = _norm(program["name"], digits=False)
    for h in history:
        if h["program_id"] == program["id"]:
            return h
        given = _norm(h["program_name"], digits=False)
        if len(given) >= 4 and (given in name or name in given):
            return h
    return None


async def similar_companies(conn: AsyncConnection, org_id: int, scores: dict[str, int],
                            k: int = SIMILAR_K) -> list[dict]:
    rows = await (await conn.execute(
        """SELECT o.id FROM ax.organization o JOIN ax.company_profile cp ON cp.organization_id = o.id
            WHERE o.is_active AND o.org_type = 'COMPANY' AND o.id <> %s""", (org_id,))).fetchall()
    out = []
    for r in rows:
        inp = await dstate.load_input(conn, r["id"])
        if inp is None:
            continue
        s = {a: v["score"] for a, v in dstate.area_scores(inp).items()}
        dist = math.sqrt(sum((s[a] - scores[a]) ** 2 for a in scores))
        out.append({"organization_id": r["id"], "distance": dist, "scores": s})
    return sorted(out, key=lambda x: (x["distance"], x["organization_id"]))[:k]


def _similar_stats(program: dict, prev_programs: list[dict], similar: list[dict],
                   history: dict[int, list[dict]]) -> dict:
    took = [(s["organization_id"], took_program(history.get(s["organization_id"], []), program)) for s in similar]
    hits = [(o, h) for o, h in took if h]
    gaps = []
    for o, h in hits:
        for prev in prev_programs:
            p = took_program(history.get(o, []), prev)
            if p and p["year"] and h["year"] and h["year"] >= p["year"]:
                gaps.append(h["year"] - p["year"])
                break
    return {"count": len(hits), "total": len(similar),
            "avg_gap_years": round(sum(gaps) / len(gaps), 1) if gaps else None}


def _readiness(stage_idx: int, review: dict | None, entry_unmet: list[dict]) -> str:
    if stage_idx == 0 and review is not None:
        if review["verdict"] == "ELIGIBLE" and not entry_unmet:
            return "IMMEDIATE"
        return "AFTER_FIX"
    return "PREPARE"


async def build(conn: AsyncConnection, org_id: int, *, concern: str | None = None,
                diagnosis: dict | None = None, review: dict | None = None) -> dict:
    diagnosis = diagnosis or await dstate.run(conn, org_id, save=False)
    scores = {a["code"]: a["score"] for a in diagnosis["areas"]}
    all_stages = await stages(conn)
    codes = [s["code"] for s in all_stages]
    current = STATE_STAGE.get(diagnosis["state_type"], "ENTRY")
    route_stages = all_stages[codes.index(current):][:len(HORIZONS)]

    programs = await route_programs(conn)
    by_stage: dict[str, list[dict]] = defaultdict(list)
    for p in programs:
        by_stage[p["stage_code"]].append(p)
    anns = await _announcements_by_program(conn, [p["id"] for p in programs])
    current_ids = sorted({a["id"] for p in anns.values() for a in p["current"]})
    if review is None:
        review = await eligibility_review.review(conn, org_id, concern=concern, announcement_ids=current_ids or None,
                                                 diagnosis=diagnosis) if current_ids else {"results": []}
    reviewed = {r["announcement_id"]: r for r in review["results"]}

    history = await _support(conn)
    mine = history.get(org_id, [])
    similar = await similar_companies(conn, org_id, scores)

    steps, not_recommended = [], []
    prev_programs: list[dict] = []
    for idx, st in enumerate(route_stages):
        cands = []
        for p in by_stage.get(st["code"], []):
            a = anns.get(p["id"], {"current": [], "latest": None})
            took = took_program(mine, p)
            base = {"program_id": p["id"], "program_code": p["program_code"], "name": p["name"],
                    "stage": st["code"]}
            if took and not p["repeatable"]:
                not_recommended.append({**base, "reason": f"이미 수혜 ({took['program_name']}"
                                                          f"{', ' + str(took['year']) if took['year'] else ''})",
                                        "fix": None})
                continue
            current_reviews = [reviewed[x["id"]] for x in a["current"] if x["id"] in reviewed]
            best = min(current_reviews, key=lambda r: (eligibility_review.ORDER[r["verdict"]],
                                                       -(r["fit"]["score"] or -1)), default=None)
            basis_ann = best or a["latest"]
            if basis_ann is None:
                not_recommended.append({**base, "reason": "근거 공고 없음 (공고 등록 후 추천)", "fix": None})
                continue
            if idx == 0 and best is not None and best["verdict"] == "INELIGIBLE":
                unmet = [c for c in best["checks"] if c["is_mandatory"] and c["result"] == "UNMET"]
                not_recommended.append({**base, "reason": "신청 불가: " + "; ".join(
                    f"{c['description']} ({c['reason']})" for c in unmet[:2]),
                    "fix": [c["question"] for c in unmet if c.get("question")] or None,
                    "announcement_id": best["announcement_id"]})
                continue
            mins = p["entry_min_scores"] or {}
            entry_unmet = [{"area": ar, "label": dstate.AREA_KO[ar], "min": m, "score": scores[ar]}
                           for ar, m in mins.items() if scores.get(ar, 0) < m]
            ready = _readiness(idx, best, entry_unmet)
            ann_id = best["announcement_id"] if best else a["latest"]["id"]
            ann_title = best["title"] if best else a["latest"]["title"]
            cands.append({
                **base, "readiness": ready, "readiness_label": READY_KO[ready],
                "announcement_id": ann_id, "announcement_title": ann_title,
                "announcement_state": best["receipt_state"] if best else a["latest"]["receipt_state"],
                "q1_label": best["q1_label"] if best else None,
                "fit_grade": best["fit"]["grade_label"] if best else None,
                "fit_score": best["fit"]["score"] if best else None,
                "entry_condition": p["entry_condition"], "entry_unmet": entry_unmet,
                "prep_tasks": list(p["prep_tasks"] or []), "expected_output": p["expected_output"],
                "todo": [t["text"] for t in best["todo"]] if best else [],
                "submit_documents": best["guide"]["submit_documents"] if best else [],
                "basis_quotes": [c["source_quote"] for c in best["checks"]
                                 if c["is_mandatory"] and c.get("source_quote")][:2] if best else [],
                "reason": _reason(p, best, entry_unmet, scores),
                "similar": _similar_stats(p, prev_programs, similar, history),
                "sort": p["sort_order"],
            })
        cands.sort(key=lambda c: (READY_ORDER[c["readiness"]], -(c["fit_score"] or -1), c["sort"]))
        picked, others = cands[:PER_STAGE], cands[PER_STAGE:]
        for c in picked + others:
            c.pop("sort")
        tasks = _stage_tasks(st, picked, scores)
        steps.append({
            "order": idx + 1, "horizon": HORIZONS[idx], "stage": st["code"], "stage_label": st["name_ko"],
            "goal": st["goal"], "is_current": idx == 0,
            "programs": picked, "other_programs": others,
            "tasks": tasks, "basis": _stage_basis(st, picked, scores, diagnosis, idx),
        })
        prev_programs = [{"id": c["program_id"], "name": c["name"]} for c in picked] or prev_programs
    return {
        "organization_id": org_id, "company_name": diagnosis["company_name"],
        "state_label": diagnosis["state_label"], "total_score": diagnosis["total_score"],
        "weakest_area": diagnosis["weakest_area"], "weakest_label": diagnosis["weakest_label"],
        "strength": diagnosis["strengths"][0] if diagnosis["strengths"] else None,
        "current_stage": current,
        "steps": steps, "not_recommended": not_recommended,
        "similar_count": len(similar),
        "summary": summary_text(diagnosis, steps),
        "notice": NOTICE,
    }


def _reason(p: dict, best: dict | None, entry_unmet: list[dict], scores: dict[str, int]) -> str:
    bits = []
    if best:
        bits.append(f"{best['q1_label']}, 적합도 {best['fit']['grade_label']}")
    if entry_unmet:
        bits.append("진입조건 미달: " + ", ".join(f"{e['label']} {e['score']}점 (기준 {e['min']}점)"
                                             for e in entry_unmet))
    elif p["entry_condition"]:
        bits.append(f"진입조건: {p['entry_condition']}")
    return " · ".join(bits)


def _stage_tasks(st: dict, picked: list[dict], scores: dict[str, int]) -> list[str]:
    tasks: list[str] = []
    for c in picked:
        for t in c["prep_tasks"][:2]:
            if t not in tasks:
                tasks.append(t)
    for ar in st["areas"]:
        if scores[ar] < 70 and dstate.AREA_TASK[ar] not in tasks:
            tasks.append(dstate.AREA_TASK[ar])
    return tasks[:3]


def _stage_basis(st: dict, picked: list[dict], scores: dict[str, int], diagnosis: dict, idx: int) -> str:
    bits = []
    weak = diagnosis["weakest_area"]
    if idx == 0 and weak in st["areas"]:
        bits.append(f"{dstate.AREA_KO[weak]} {scores[weak]}점(최저)")
    else:
        bits += [f"{dstate.AREA_KO[a]} {scores[a]}점" for a in st["areas"]]
    if picked:
        sim = picked[0]["similar"]
        if sim["total"]:
            bits.append(f"유사 기업 {sim['count']}/{sim['total']}개사가 {picked[0]['name']} 참여")
        if sim["avg_gap_years"] is not None and idx > 0:
            bits.append(f"이전 단계 사업 후 평균 {sim['avg_gap_years']}년")
    return " · ".join(bits)


def summary_text(diagnosis: dict, steps: list[dict]) -> str:
    head = ""
    if diagnosis["strengths"]:
        s = diagnosis["strengths"][0]
        head = f"{s['label']} 강점({s['score']}점)을 바탕으로 "
    parts = []
    for st in steps:
        names = "·".join(c["name"] for c in st["programs"])
        when = st["horizon"].split(" ·")[0]
        parts.append(f"{when}에는 {names + ' 참여로' if names else '준비과제 수행으로'} {st['goal']}")
    if not parts:
        return "추천할 경로가 없음. 사업 연계 기준과 공고 등록이 필요함."
    return head + ", ".join(parts) + "의 순서로 가는 경로를 권고함."


async def rules(conn: AsyncConnection) -> dict:
    progs = await (await conn.execute(
        """SELECT p.id AS program_id, p.program_code, p.name, p.purpose, r.stage_code, r.next_program_ids,
                  r.entry_condition, r.entry_min_scores, r.prep_tasks, r.expected_output, r.repeatable,
                  r.sort_order, r.updated_at,
                  (SELECT count(*) FROM ax.announcement a WHERE a.program_id = p.id AND a.status = 'PUBLISHED')
                      AS announcement_count
             FROM ax.program p LEFT JOIN ax.program_route r ON r.program_id = p.id
            WHERE p.is_active ORDER BY r.stage_code NULLS LAST, r.sort_order, p.id""")).fetchall()
    names = {p["program_id"]: p["name"] for p in progs}
    for p in progs:
        p["next_programs"] = [{"program_id": i, "name": names.get(i)} for i in (p["next_program_ids"] or [])]
        p["updated_at"] = p["updated_at"].isoformat() if p["updated_at"] else None
    return {"stages": await stages(conn), "programs": progs,
            "areas": [{"code": c, "label": l} for c, l in dstate.AREAS]}


async def save_program_route(conn: AsyncConnection, program_id: int, data: dict, user_id: int) -> None:
    if not await (await conn.execute("SELECT 1 FROM ax.program WHERE id = %s", (program_id,))).fetchone():
        raise LookupError(program_id)
    nxt = list(dict.fromkeys(data["next_program_ids"]))
    if program_id in nxt:
        raise ValueError("다음 연계사업에 자기 자신을 넣을 수 없음")
    if nxt:
        found = {r["id"] for r in await (await conn.execute(
            "SELECT id FROM ax.program WHERE id = ANY(%s)", (nxt,))).fetchall()}
        if missing := [i for i in nxt if i not in found]:
            raise ValueError(f"없는 사업: {missing}")
    await conn.execute(
        """INSERT INTO ax.program_route (program_id, stage_code, next_program_ids, entry_condition, entry_min_scores,
                                         prep_tasks, expected_output, repeatable, sort_order, updated_by, updated_at)
           VALUES (%(pid)s, %(stage_code)s, %(nxt)s, %(entry_condition)s, %(mins)s, %(prep_tasks)s,
                   %(expected_output)s, %(repeatable)s, %(sort_order)s, %(uid)s, now())
           ON CONFLICT (program_id) DO UPDATE SET stage_code = EXCLUDED.stage_code,
               next_program_ids = EXCLUDED.next_program_ids, entry_condition = EXCLUDED.entry_condition,
               entry_min_scores = EXCLUDED.entry_min_scores, prep_tasks = EXCLUDED.prep_tasks,
               expected_output = EXCLUDED.expected_output, repeatable = EXCLUDED.repeatable,
               sort_order = EXCLUDED.sort_order, updated_by = EXCLUDED.updated_by, updated_at = now()""",
        {**data, "pid": program_id, "nxt": nxt, "mins": Jsonb(data["entry_min_scores"]), "uid": user_id})
