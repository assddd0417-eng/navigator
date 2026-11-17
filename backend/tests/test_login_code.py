"""회사 정보 화면 본인 확인 코드."""
import re

import psycopg
import pytest

from app.config import get_settings
from app.services import mailer
from app.services.ratelimit import limiter
from tests.conftest import TEST_URL
from tests.test_navigator_matching import _seed

BRN, EMAIL = "9998100015", "contact@hanbit.example"


def _q(sql, *args):
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        cur = conn.execute(sql, args)
        return cur.fetchall() if cur.description else []


def _age_codes():
    """1분 재발송 제한을 건너뛴다."""
    _q("UPDATE ax.company_login_code SET created_at = created_at - interval '2 minutes'")


def _last_code() -> str:
    return re.search(r"확인 코드 (\d{6})", mailer.OUTBOX[-1].subject).group(1)


@pytest.fixture
def fresh(database):
    limiter.reset()
    _seed()
    _q("DELETE FROM ax.company_login_code")
    yield


async def test_code_flow(client, fresh):
    r = await client.post(f"/navigator/companies/{BRN}/login-code")
    assert r.status_code == 202, r.text
    assert r.json()["sent_to"] == "c***@hanbit.example" and "dev_code" not in r.json()
    mail = mailer.OUTBOX[-1]
    assert mail.to == EMAIL and re.search(r"\b\d{6}\b", mail.body)
    code = _last_code()
    assert _q("SELECT code_hash <> %s FROM ax.company_login_code", code)[0][0]   # 코드 원문은 저장 안 함

    # 1분 안에 다시 받기는 막음
    again = await client.post(f"/navigator/companies/{BRN}/login-code")
    assert again.status_code == 429 and "Retry-After" in again.headers

    wrong = "000000" if code != "000000" else "111111"
    assert (await client.post(f"/navigator/companies/{BRN}/login", json={"code": wrong})).status_code == 400
    r = await client.post(f"/navigator/companies/{BRN}/login", json={"code": code})
    assert r.status_code == 200, r.text
    h = {"X-Manage-Token": r.json()["token"]}
    assert (await client.get("/navigator/manage/profile", headers=h)).json()["organization_id"] == 101

    # 한 번 쓴 코드는 다시 못 씀
    assert (await client.post(f"/navigator/companies/{BRN}/login", json={"code": code})).status_code == 410


async def test_new_code_revokes_old_and_attempt_limit(client, fresh):
    await client.post(f"/navigator/companies/{BRN}/login-code")
    old = _last_code()
    _age_codes()
    await client.post(f"/navigator/companies/{BRN}/login-code")
    new = _last_code()
    if old != new:
        assert (await client.post(f"/navigator/companies/{BRN}/login", json={"code": old})).status_code in (400, 410)

    _age_codes()
    await client.post(f"/navigator/companies/{BRN}/login-code")
    code = _last_code()
    wrong = "000000" if code != "000000" else "111111"
    statuses = [(await client.post(f"/navigator/companies/{BRN}/login", json={"code": wrong})).status_code
                for _ in range(5)]
    assert statuses == [400, 400, 400, 400, 410]
    # 5번 틀리면 맞는 코드도 안 됨
    assert (await client.post(f"/navigator/companies/{BRN}/login", json={"code": code})).status_code == 410


async def test_expired_code(client, fresh):
    await client.post(f"/navigator/companies/{BRN}/login-code")
    code = _last_code()
    _q("UPDATE ax.company_login_code SET expires_at = now() - interval '1 second'")
    assert (await client.post(f"/navigator/companies/{BRN}/login", json={"code": code})).status_code == 410


async def test_rules(client, fresh, monkeypatch):
    # 사업자번호만으로 여는 길은 없음
    assert (await client.post(f"/navigator/companies/{BRN}/open")).status_code in (404, 405)
    # 형식
    assert (await client.post(f"/navigator/companies/{BRN}/login", json={"code": "12ab56"})).status_code == 422
    # 없는 기업
    assert (await client.post("/navigator/companies/9998400049/login-code")).status_code in (404, 409, 202)
    # 등록 이메일 없는 기업
    _q("UPDATE ax.company_profile SET registered_email = NULL WHERE organization_id = 102")
    try:
        r = await client.post("/navigator/companies/9998200026/login-code")
        assert r.status_code == 409 and "이메일" in r.json()["detail"]
    finally:
        _q("UPDATE ax.company_profile SET registered_email = 'rnd@nuri.example' WHERE organization_id = 102")
    # 로컬 시연: 응답에 코드
    monkeypatch.setattr(get_settings(), "navigator_dev_expose_link", True)
    r = await client.post(f"/navigator/companies/{BRN}/login-code")
    assert r.json()["dev_code"] == _last_code()


async def test_fit_levels(client, monkeypatch):
    r = (await client.get("/navigator/fit-levels")).json()
    assert r == {"embedder": "hash", "high": 0.45, "mid": 0.25}
    monkeypatch.setattr(get_settings(), "embedder", "bge_m3")
    assert (await client.get("/navigator/fit-levels")).json()["high"] == 0.60
    monkeypatch.setattr(get_settings(), "navigator_fit_high", 0.7)
    assert (await client.get("/navigator/fit-levels")).json()["high"] == 0.7
