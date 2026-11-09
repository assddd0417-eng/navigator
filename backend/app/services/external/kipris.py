"""KIPRIS Plus 특허 조회. 사업자번호 검색이 없어 출원인 이름(또는 특허고객번호)으로 찾는다.

mock 은 fixtures/kipris_mock.json (사업자번호별). live 는 KIPRIS Plus getAdvancedSearch (KIPRIS_ACCESS_KEY).
live 는 키 발급 후 응답 필드 확인 필요.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime

from app.config import get_settings
from app.services.external.base import (
    ConnectorUnavailable, http_get_text, load_fixture, normalize_company_name)

SOURCE_CODE = "KIPRIS"
LIVE_URL = "http://plus.kipris.or.kr/kipo-api/kipi/patUtiModInfoSearchSevice/getAdvancedSearch"
_STATUS = {"등록": "REGISTERED", "공개": "APPLIED", "출원": "APPLIED", "거절": "LAPSED", "소멸": "LAPSED",
           "취하": "LAPSED", "포기": "LAPSED", "무효": "LAPSED"}


@dataclass
class PatentRecord:
    application_no: str
    title: str
    status: str
    ipc_codes: list[str]
    applicant: str
    applied_on: date | None = None
    registration_no: str | None = None
    registered_on: date | None = None
    abstract: str | None = None
    applicant_code: str | None = None

    def raw(self) -> dict:
        return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in self.__dict__.items()}


def _date(v: str | None) -> date | None:
    v = (v or "").replace("-", "").replace(".", "").strip()
    return datetime.strptime(v[:8], "%Y%m%d").date() if len(v) >= 8 and v[:8].isdigit() else None


def _app_no(v: str) -> str:
    d = "".join(ch for ch in v if ch.isdigit())
    return f"{d[:2]}-{d[2:6]}-{d[6:]}" if len(d) == 13 else v


class MockKiprisConnector:
    mode = "mock"

    def __init__(self, data: dict):
        self.data = data

    def patents(self, company_name: str, bizno: str, applicant_code: str | None = None) -> list[PatentRecord]:
        rows = self.data.get(bizno, [])
        return [PatentRecord(**{**r, "applied_on": _date(r.get("applied_on")),
                                "registered_on": _date(r.get("registered_on"))}) for r in rows]


class LiveKiprisConnector:
    mode = "live"

    def __init__(self, key: str | None):
        if not key:
            raise ConnectorUnavailable("KIPRIS_ACCESS_KEY 없음")
        self.key = key

    def patents(self, company_name: str, bizno: str, applicant_code: str | None = None) -> list[PatentRecord]:
        out: list[PatentRecord] = []
        want = normalize_company_name(company_name)
        for page in range(1, 11):   # 최대 500건
            xml = http_get_text(LIVE_URL, {"applicant": applicant_code or company_name, "patent": "true",
                                           "utility": "false", "numOfRows": 50, "pageNo": page,
                                           "ServiceKey": self.key})
            items = ET.fromstring(xml).findall(".//item")
            for it in items:
                f = {c.tag: (c.text or "").strip() for c in it}
                # 이름 검색은 부분 일치라 출원인 이름이 정확히 같은 것만
                if not applicant_code and normalize_company_name(f.get("applicantName", "")) != want:
                    continue
                status = next((v for k, v in _STATUS.items() if k in f.get("registerStatus", "")), "APPLIED")
                reg_no = f.get("registerNumber") or None
                if status == "REGISTERED" and not reg_no:
                    status = "APPLIED"
                out.append(PatentRecord(
                    application_no=_app_no(f.get("applicationNumber", "")), title=f.get("inventionTitle", ""),
                    status=status, ipc_codes=[x.strip() for x in f.get("ipcNumber", "").split("|") if x.strip()],
                    applicant=f.get("applicantName", ""), applied_on=_date(f.get("applicationDate")),
                    registration_no=reg_no, registered_on=_date(f.get("registerDate")),
                    abstract=f.get("astrtCont") or None))
            if len(items) < 50:
                break
        return out


def get_kipris_connector() -> MockKiprisConnector | LiveKiprisConnector:
    s = get_settings()
    mode = s.source_kipris.lower()
    if mode == "mock":
        return MockKiprisConnector(load_fixture("kipris_mock.json")["patents"])
    if mode == "live":
        return LiveKiprisConnector(s.kipris_access_key)
    raise ValueError(f"SOURCE_KIPRIS={mode} (mock|live)")
