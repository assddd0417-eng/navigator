"""통합 테스트 픽스처: 테스트 DB 를 새로 만들고 마이그레이션 + 기본 데이터를 넣는다.

TEST_ADMIN_DATABASE_URL (기본: postgresql://postgres@localhost:5432/postgres) 로 접속해
navigator_test DB 를 DROP/CREATE 한다. 운영 DB 를 가리키지 않도록 주의.
"""
import os
import subprocess
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ADMIN_URL = os.environ.get("TEST_ADMIN_DATABASE_URL", "postgresql://postgres@localhost:5432/postgres")
TEST_DB = "navigator_test"
TEST_URL = make_conninfo(ADMIN_URL, dbname=TEST_DB)
ROOT = Path(__file__).resolve().parents[2]

os.environ["DATABASE_URL"] = TEST_URL
os.environ.setdefault("EMBEDDER", "hash")
os.environ["COLLECT_AUTO_MINUTES"] = "0"

SEED = """
SET search_path = ax, public;
INSERT INTO department (id, dept_code, name) OVERRIDING SYSTEM VALUE VALUES (1,'D-BIZ','사업지원팀');
INSERT INTO app_user (id, login_id, name, department_id, clearance_code) OVERRIDING SYSTEM VALUE VALUES
  (1,'staff','공고담당',1,'INTERNAL'), (2,'viewer','열람자',1,'PUBLIC');
INSERT INTO user_role (user_id, role_code) VALUES (1,'STAFF');
INSERT INTO program (id, program_code, name, program_type_code, purpose) OVERRIDING SYSTEM VALUE VALUES
  (1,'P-LOC','부품국산화개발지원','PARTS_LOCALIZATION','수입 부품의 국산화로 공급망 안정'),
  (2,'P-CORE','핵심기술개발','CORE_TECH','미래 핵심기술 확보');
SELECT setval(pg_get_serial_sequence('ax.department','id'), 10);
SELECT setval(pg_get_serial_sequence('ax.app_user','id'), 10);
SELECT setval(pg_get_serial_sequence('ax.organization','id'), 10);
SELECT setval(pg_get_serial_sequence('ax.program','id'), 10);
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


async def manage_token(client, brn: str) -> str:
    """확인 코드를 받아(메일 mock) 회사 정보 화면 관리 토큰을 얻는다."""
    import re

    from app.services import mailer
    from app.services.ratelimit import limiter

    limiter.reset()
    with psycopg.connect(TEST_URL, autocommit=True) as conn:   # 1분에 한 번 제한을 테스트에서는 건너뜀
        conn.execute("UPDATE ax.company_login_code SET created_at = created_at - interval '2 minutes'")
    r = await client.post(f"/navigator/companies/{brn}/login-code")
    assert r.status_code == 202, r.text
    code = re.search(r"확인 코드 (\d{6})", mailer.OUTBOX[-1].subject).group(1)
    r = await client.post(f"/navigator/companies/{brn}/login", json={"code": code})
    assert r.status_code == 200, r.text
    return r.json()["token"]
