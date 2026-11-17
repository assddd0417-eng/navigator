"""옛 DB(relay_ax)에서 Navigator 데이터만 새 DB(navigator)로 옮긴다. 한 번만 쓰는 스크립트.

    ~/navigator/backend/.venv/bin/python copy_from_old_db.py --dry-run   # 옮길 건수만 확인
    ~/navigator/backend/.venv/bin/python copy_from_old_db.py             # 실제로 옮김

- 옮기는 것: 회사 정보 화면으로 등록한 기업(등록 경로가 있는 기업)과 그 특허·인증·등급·R&D·제품·증빙 등,
  공고·지원 조건·첨부, 공고문 원문(공고·증빙에 연결된 문서만), 알림 받는 사람·보낸 알림, 매칭 결과·답변,
  참여 권유 메일, 외부 수집 기록.
- 옮기지 않는 것: 성과카드·과제·기획수요 등 다른 서비스 데이터, 사용자 계정, 감사 로그, 벡터.
  벡터는 옮긴 뒤 `python -m app.reembed` 로 다시 만든다.
- 새 DB 의 Navigator 데이터(시드 포함)는 지우고 옛 DB 것으로 바꾼다. 사용자·부서·코드표는 그대로 둔다.
- 옛 데이터에 남아 있는 사용자 ID 는 새 DB 의 기관 담당자(1)로 바꾼다.
"""
from __future__ import annotations

import argparse
import sys

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

# 옮길 표와 옛 DB 에서 고르는 조건. {O} = 옮길 기관 ID, {D} = 옮길 문서 ID, {E} = 옮길 근거 ID
TABLES: list[tuple[str, str]] = [
    ("organization", "id = ANY(%(O)s)"),
    ("source_document", "id = ANY(%(D)s)"),
    ("document_section", "document_id = ANY(%(D)s)"),
    ("document_chunk", "document_id = ANY(%(D)s)"),
    ("evidence", "id = ANY(%(E)s)"),
    ("external_source", "true"),
    ("external_fetch_job", "organization_id IS NULL OR organization_id = ANY(%(O)s)"),
    ("external_raw_record", "organization_id IS NULL OR organization_id = ANY(%(O)s)"),
    ("company_profile", "organization_id = ANY(%(O)s)"),
    ("company_patent", "organization_id = ANY(%(O)s)"),
    ("company_evidence", "organization_id = ANY(%(O)s)"),
    ("company_certification", "organization_id = ANY(%(O)s)"),
    ("company_credit_rating", "organization_id = ANY(%(O)s)"),
    ("company_rnd_history", "organization_id = ANY(%(O)s)"),
    ("company_technology", "organization_id = ANY(%(O)s)"),
    ("company_product", "organization_id = ANY(%(O)s)"),
    ("company_access_link", "organization_id = ANY(%(O)s)"),
    ("company_login_code", "organization_id = ANY(%(O)s)"),
    ("company_field_source", "organization_id = ANY(%(O)s)"),
    ("company_external_id", "organization_id = ANY(%(O)s)"),
    ("announcement", "true"),
    ("announcement_requirement", "true"),
    ("announcement_tech_need", "true"),
    ("announcement_attachment", "true"),
    ("company_support_history", "organization_id = ANY(%(O)s)"),
    ("alert_subscription", "organization_id = ANY(%(O)s)"),
    ("company_match_run", "organization_id IS NULL OR organization_id = ANY(%(O)s)"),
    ("company_recommendation", "organization_id = ANY(%(O)s)"),
    ("company_recommendation_score", "true"),
    ("company_recommendation_evidence", "true"),
    ("eligibility_check", "true"),
    ("eligibility_answer", "organization_id = ANY(%(O)s)"),
    ("alert_notification", "organization_id = ANY(%(O)s)"),
    ("outreach_message", "organization_id = ANY(%(O)s)"),
]
# 새 DB 에서 비우는 표 (위 표 + 벡터)
CLEAR = [t for t, _ in TABLES] + ["company_embedding", "announcement_embedding", "chunk_embedding"]
# 코드표에 없는 값을 바꿀 기본값
CODE_FALLBACK = {"code_document_type": "OTHER", "code_source_system": "MANUAL"}
STAFF_USER_ID = 1


def q(conn, query, params=None):
    return conn.execute(query, params or {}).fetchall()


def ids(conn, query, params=None) -> list[int]:
    return sorted({r["id"] for r in q(conn, query, params) if r["id"] is not None})


def table_exists(conn, name: str) -> bool:
    return q(conn, "SELECT to_regclass(%s) AS t", (f"ax.{name}",))[0]["t"] is not None


def columns(conn, table: str) -> dict[str, str]:
    rows = q(conn, """SELECT column_name, data_type FROM information_schema.columns
                      WHERE table_schema = 'ax' AND table_name = %s AND is_generated = 'NEVER'""", (table,))
    return {r["column_name"]: r["data_type"] for r in rows}


def foreign_keys(conn) -> list[dict]:
    return q(conn, """
        SELECT tc.table_name AS tbl, kcu.column_name AS col, ccu.table_name AS ref, ccu.column_name AS ref_col,
               c.is_nullable = 'YES' AS nullable
          FROM information_schema.table_constraints tc
          JOIN information_schema.key_column_usage kcu
            ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema
          JOIN information_schema.constraint_column_usage ccu
            ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
          JOIN information_schema.columns c
            ON c.table_schema = 'ax' AND c.table_name = tc.table_name AND c.column_name = kcu.column_name
         WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'ax'""")


def pick_sets(old) -> dict[str, list[int]]:
    orgs = ids(old, """
        SELECT organization_id AS id FROM ax.company_profile WHERE registration_channel IS NOT NULL
        UNION SELECT agency_org_id FROM ax.announcement""")
    ev = ids(old, """
        SELECT evidence_id AS id FROM ax.announcement_requirement
        UNION SELECT evidence_id FROM ax.company_recommendation_evidence""")
    docs = ids(old, """
        SELECT document_id AS id FROM ax.announcement
        UNION SELECT evidence_document_id FROM ax.company_certification WHERE organization_id = ANY(%(O)s)
        UNION SELECT evidence_document_id FROM ax.company_credit_rating WHERE organization_id = ANY(%(O)s)
        UNION SELECT document_id FROM ax.evidence WHERE id = ANY(%(E)s)""", {"O": orgs, "E": ev})
    return {"O": orgs, "D": docs, "E": ev}


def model_map(old, new) -> dict[int, int]:
    new_rows = q(new, "SELECT id, name FROM ax.embedding_model")
    by_name = {r["name"]: r["id"] for r in new_rows}
    hash_id = next((r["id"] for r in new_rows if "hash" in r["name"]), None)
    out = {}
    for r in q(old, "SELECT id, name FROM ax.embedding_model"):
        out[r["id"]] = by_name.get(r["name"]) or (hash_id if "hash" in r["name"] else None)
    return out


def program_map(old, new, dry: bool) -> dict[int, int]:
    """사업은 program_code 로 맞춘다. 새 DB 에 없는 사업은 만든다."""
    by_code = {r["program_code"]: r["id"] for r in q(new, "SELECT id, program_code FROM ax.program")}
    used = ids(old, "SELECT program_id AS id FROM ax.announcement UNION SELECT program_id FROM ax.source_document "
                    "WHERE id = ANY(%(D)s)", {"D": pick_sets(old)["D"]})
    out = {}
    for r in q(old, "SELECT id, program_code, name, program_type_code, purpose FROM ax.program WHERE id = ANY(%s)", (used,)):
        if r["program_code"] not in by_code and not dry:
            by_code[r["program_code"]] = new.execute(
                "INSERT INTO ax.program (program_code, name, program_type_code, purpose) VALUES (%s, %s, %s, %s) RETURNING id",
                (r["program_code"], r["name"], r["program_type_code"], r["purpose"])).fetchone()["id"]
        out[r["id"]] = by_code.get(r["program_code"])
    return out


def adapt(v, data_type: str):
    return Jsonb(v) if data_type == "jsonb" and v is not None else v


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default="postgresql://localhost:5432/relay_ax")
    ap.add_argument("--new", default="postgresql://localhost:5432/navigator")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    old = psycopg.connect(a.old, row_factory=dict_row)
    new = psycopg.connect(a.new, row_factory=dict_row)
    old.execute("SET TRANSACTION READ ONLY")
    sets = pick_sets(old)
    print(f"옮길 기관 {len(sets['O'])}곳, 문서 {len(sets['D'])}건")

    fks = foreign_keys(new)
    fk_by_col = {(f["tbl"], f["col"]): f for f in fks}
    codes = {}
    for f in fks:
        if f["ref"].startswith("code_") or f["ref"] == "app_role":
            codes.setdefault(f["ref"], {r["v"] for r in q(new, sql.SQL("SELECT {} AS v FROM ax.{}").format(
                sql.Identifier(f["ref_col"]), sql.Identifier(f["ref"])))})

    new.execute("SET session_replication_role = replica")   # 옮기는 동안 FK·트리거 끔 (감사 로그도 안 남김)
    if not a.dry_run:
        for t in CLEAR:
            new.execute(sql.SQL("DELETE FROM ax.{}").format(sql.Identifier(t)))
    models = model_map(old, new)
    programs = program_map(old, new, a.dry_run)

    total = {}
    for table, where in TABLES:
        if not table_exists(old, table):
            continue
        old_cols, new_cols = columns(old, table), columns(new, table)
        cols = [c for c in new_cols if c in old_cols]
        rows = q(old, sql.SQL("SELECT {} FROM ax.{} WHERE " + where).format(
            sql.SQL(", ").join(map(sql.Identifier, cols)), sql.Identifier(table)), sets)
        total[table] = len(rows)
        if a.dry_run or not rows:
            continue
        for r in rows:
            for c in cols:
                v = r[c]
                f = fk_by_col.get((table, c))
                if v is None or f is None:
                    continue
                if f["ref"] == "app_user":
                    r[c] = STAFF_USER_ID
                elif f["ref"] == "department":
                    r[c] = 1
                elif f["ref"] == "program":
                    r[c] = programs.get(v)
                elif f["ref"] == "embedding_model":
                    r[c] = models.get(v)
                elif f["ref"] == "tech_taxonomy":
                    r[c] = None
                elif f["ref"] in codes and v not in codes[f["ref"]]:
                    if f["ref"] not in CODE_FALLBACK:
                        sys.exit(f"{table}.{c} 값 {v!r} 가 새 DB {f['ref']} 에 없음")
                    r[c] = CODE_FALLBACK[f["ref"]]
        stmt = sql.SQL("INSERT INTO ax.{} ({}) OVERRIDING SYSTEM VALUE VALUES ({})").format(
            sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, cols)),
            sql.SQL(", ").join(sql.Placeholder() * len(cols)))
        with new.cursor() as cur:
            cur.executemany(stmt, [[adapt(r[c], new_cols[c]) for c in cols] for r in rows])

    for t, n in total.items():
        print(f"  {t:34s} {n}")
    if a.dry_run:
        print("--dry-run: 아무것도 바꾸지 않았습니다")
        return

    # 옮기지 않은 행을 가리키는 값 정리: 비워도 되는 칸은 비우고, 필수 칸이면 그 행을 뺀다
    for _ in range(5):
        changed = 0
        for f in fks:
            orphan = sql.SQL("{c} IS NOT NULL AND NOT EXISTS (SELECT 1 FROM ax.{r} p WHERE p.{rc} = t.{c})").format(
                c=sql.Identifier(f["col"]), r=sql.Identifier(f["ref"]), rc=sql.Identifier(f["ref_col"]))
            if f["nullable"]:
                stmt = sql.SQL("UPDATE ax.{t} t SET {c} = NULL WHERE ").format(
                    t=sql.Identifier(f["tbl"]), c=sql.Identifier(f["col"])) + orphan
            else:
                stmt = sql.SQL("DELETE FROM ax.{t} t WHERE ").format(t=sql.Identifier(f["tbl"])) + orphan
            n = new.execute(stmt).rowcount
            if n:
                print(f"  정리: {f['tbl']}.{f['col']} {n}건 ({'비움' if f['nullable'] else '행 제외'})")
                changed += n
        if not changed:
            break

    # 번호 이어 붙이기
    for r in q(new, """SELECT table_name, column_name FROM information_schema.columns
                       WHERE table_schema = 'ax' AND is_identity = 'YES'"""):
        new.execute(sql.SQL("SELECT setval(pg_get_serial_sequence({q}, {c}), GREATEST(10, COALESCE(max({ci}), 1))) FROM ax.{t}").format(
            q=sql.Literal(f"ax.{r['table_name']}"), c=sql.Literal(r["column_name"]),
            ci=sql.Identifier(r["column_name"]), t=sql.Identifier(r["table_name"])))
    new.execute("SET session_replication_role = origin")
    new.commit()
    print("완료. 다음: cd ~/navigator/backend && .venv/bin/python -m app.reembed")


if __name__ == "__main__":
    main()
