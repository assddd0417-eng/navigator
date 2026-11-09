"""OpenDART 재무·직원 수. 상장사·외부감사 대상만 있다.

mock 은 fixtures/dart_mock.json (사업자번호별). live 는 opendart.fss.or.kr (DART_API_KEY).
고유번호(corp_code)는 회사명으로 후보를 찾고 company.json 의 사업자번호가 같은 것으로 정한다.
"""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from app.config import get_settings
from app.services.external.base import (
    ConnectorUnavailable, http_get_bytes, http_get_json, load_fixture, normalize_company_name)

SOURCE_CODE = "DART"
BASE = "https://opendart.fss.or.kr/api"
REVENUE_ACCOUNTS = ("매출액", "수익(매출액)", "영업수익", "매출")


@dataclass
class Financials:
    corp_code: str
    year: int
    revenue_krw: int | None
    employee_count: int | None
    raw: dict


def _int(v) -> int | None:
    try:
        return int(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


class MockDartConnector:
    mode = "mock"

    def __init__(self, data: dict):
        self.data = data

    def find_corp_code(self, company_name: str, bizno: str) -> str | None:
        return (self.data.get(bizno) or {}).get("corp_code")

    def financials(self, corp_code: str, year: int | None = None) -> Financials | None:
        rec = next((r for r in self.data.values() if r["corp_code"] == corp_code), None)
        if rec is None:
            return None
        return Financials(corp_code, rec["year"], rec.get("revenue_krw"), rec.get("employee_count"), rec)


class LiveDartConnector:
    mode = "live"

    def __init__(self, key: str | None):
        if not key:
            raise ConnectorUnavailable("DART_API_KEY 없음")
        self.key = key

    def _get(self, path: str, **params) -> dict:
        body = http_get_json(f"{BASE}/{path}", {"crtfc_key": self.key, **params})
        status = body.get("status")
        if status == "013":       # 조회된 데이터 없음
            return {}
        if status != "000":
            raise ConnectorUnavailable(f"DART {path} status={status} {body.get('message', '')}")
        return body

    @lru_cache(maxsize=1)
    def _corp_list(self) -> list[tuple[str, str]]:
        data = http_get_bytes(f"{BASE}/corpCode.xml", {"crtfc_key": self.key})
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            root = ET.fromstring(z.read(z.namelist()[0]))
        return [(e.findtext("corp_code") or "", e.findtext("corp_name") or "") for e in root.iter("list")]

    def find_corp_code(self, company_name: str, bizno: str) -> str | None:
        want = normalize_company_name(company_name)
        for code, name in self._corp_list():
            if normalize_company_name(name) == want:
                info = self._get("company.json", corp_code=code)
                if (info.get("bizr_no") or "").replace("-", "") == bizno:
                    return code
        return None

    def financials(self, corp_code: str, year: int | None = None) -> Financials | None:
        # 사업보고서는 다음 해 3월 말 이후 나온다
        years = [year] if year else [date.today().year - 1, date.today().year - 2]
        for y in years:
            fin = self._get("fnlttSinglAcnt.json", corp_code=corp_code, bsns_year=y, reprt_code="11011")
            if not fin:
                continue
            rows = fin.get("list") or []
            revenue = None
            for fs in ("CFS", "OFS"):   # 연결 우선
                hit = next((r for r in rows if r.get("fs_div") == fs and r.get("account_nm") in REVENUE_ACCOUNTS), None)
                if hit:
                    revenue = _int(hit.get("thstrm_amount"))
                    break
            emp = self._get("empSttus.json", corp_code=corp_code, bsns_year=y, reprt_code="11011")
            employees = sum(_int(r.get("sm")) or 0 for r in emp.get("list") or []) or None
            return Financials(corp_code, y, revenue, employees,
                              {"fnlttSinglAcnt": rows, "empSttus": emp.get("list") or []})
        return None


def get_dart_connector() -> MockDartConnector | LiveDartConnector:
    s = get_settings()
    mode = s.source_dart.lower()
    if mode == "mock":
        return MockDartConnector(load_fixture("dart_mock.json")["companies"])
    if mode == "live":
        return LiveDartConnector(s.dart_api_key)
    raise ValueError(f"SOURCE_DART={mode} (mock|live)")
