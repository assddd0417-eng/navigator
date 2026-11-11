"""통합 테스트 픽스처: 테스트 DB 를 새로 만들고 마이그레이션 + 기본 데이터를 넣는다.

TEST_ADMIN_DATABASE_URL (기본: postgresql://postgres@localhost:5432/postgres) 로 접속해
relay_ax_test DB 를 DROP/CREATE 한다. 운영 DB 를 가리키지 않도록 주의.
"""
import os
import subprocess
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ADMIN_URL = os.environ.get("TEST_ADMIN_DATABASE_URL", "postgresql://postgres@localhost:5432/postgres")
TEST_DB = "relay_ax_test"
TEST_URL = make_conninfo(ADMIN_URL, dbname=TEST_DB)
ROOT = Path(__file__).resolve().parents[2]  # relay-ax-db/

os.environ["DATABASE_URL"] = TEST_URL
os.environ.setdefault("EMBEDDER", "hash")
os.environ.setdefault("RATIONALE_GENERATOR", "template")  # 키가 있는 개발 PC 에서도 테스트가 실제 LLM 을 부르지 않도록

SEED = """
SET search_path = ax, public;
INSERT INTO department (id, dept_code, name) OVERRIDING SYSTEM VALUE VALUES
  (1,'D-PLAN','과제기획팀'), (2,'D-C4I','지휘정찰기술팀'), (3,'D-COMM','무인미래통신기술팀');
INSERT INTO app_user (id, login_id, name, department_id, clearance_code) VALUES
  (1,'planner','기획담당',1,'RESTRICTED'), (2,'reviewer','부서검토자',3,'RESTRICTED'),
  (3,'expert','기술전문가',2,'RESTRICTED'), (4,'curator','카드관리자',1,'RESTRICTED'),
  (5,'viewer','열람자',2,'PUBLIC'), (6,'agency','정책기획 열람자',1,'RESTRICTED');
INSERT INTO user_role (user_id, role_code) VALUES
  (1,'PLANNER'), (2,'DEPT_REVIEWER'), (3,'EXPERT'), (4,'CURATOR'), (5,'VIEWER'), (6,'VIEWER');
-- 기획팀은 통신팀 소관 자료 열람 가능
INSERT INTO department_access_grant (grantee_dept_id, target_dept_id, max_security_code) VALUES (1,3,'RESTRICTED');
INSERT INTO organization (id, name, org_type) VALUES (1,'(주)테스트방산','COMPANY'), (2,'국방기술연구원','RESEARCH_INSTITUTE');
INSERT INTO program (id, program_code, name, program_type_code, purpose, owner_dept_id) VALUES
  (1,'P-LOC','부품국산화개발지원','PARTS_LOCALIZATION','수입 부품의 국산화로 공급망 안정',1),
  (2,'P-CORE','핵심기술개발','CORE_TECH','미래 핵심기술 확보',1);
INSERT INTO weapon_system (id, system_code, name) VALUES (1,'WS-001','소형전술드론'), (2,'WS-002','차륜형장갑차');
INSERT INTO item (id, item_no, name, is_part, is_imported) VALUES (1,'ITM-0001','항재밍 데이터링크 모뎀',true,true);
INSERT INTO project (id, project_no, title, program_id, lead_org_id, department_id, status_code, end_date) VALUES
  (1,'PRJ-2022-001','소형 무인기용 항재밍 데이터링크 개발',2,2,3,'COMPLETED','2024-12-31'),
  (2,'PRJ-2021-007','전술 배터리 열관리 기술',2,2,2,'COMPLETED','2023-06-30'),
  (3,'PRJ-2023-004','EO/IR 영상 기반 표적 자동탐지',2,2,2,'COMPLETED','2025-06-30');
SELECT setval(pg_get_serial_sequence('ax.department','id'), 10);
SELECT setval(pg_get_serial_sequence('ax.app_user','id'), 10);
SELECT setval(pg_get_serial_sequence('ax.organization','id'), 10);
SELECT setval(pg_get_serial_sequence('ax.program','id'), 10);
SELECT setval(pg_get_serial_sequence('ax.weapon_system','id'), 10);
SELECT setval(pg_get_serial_sequence('ax.item','id'), 10);
SELECT setval(pg_get_serial_sequence('ax.project','id'), 10);
"""


@pytest.fixture(scope="session", autouse=True)
def database():
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {TEST_DB}")
    env = {**os.environ, "DATABASE_URL": _psql_url(TEST_URL)}
    subprocess.run([str(ROOT / "scripts" / "migrate.sh")], check=True, env=env, capture_output=True)
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        conn.execute(SEED)
    yield TEST_URL


def _psql_url(conninfo: str) -> str:
    """psql 이 받는 URI 형식으로 변환 (소켓 경로 host 포함)."""
    d = conninfo_to_dict(conninfo)
    user = d.get("user", "")
    if d.get("password"):
        user = f"{user}:{d['password']}"
    host = d.get("host", "localhost")
    port = d.get("port", "5432")
    if host.startswith("/"):
        return f"postgresql://{user}@/{d['dbname']}?host={host}&port={port}"
    return f"postgresql://{user}@{host}:{port}/{d['dbname']}"


@pytest.fixture(scope="session")
async def client(database):
    import httpx

    from app.db import close_pool
    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await close_pool()


def as_user(user_id: int) -> dict[str, str]:
    return {"X-User-Id": str(user_id)}
