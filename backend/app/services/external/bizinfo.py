"""기업마당 지원사업 공고. 키워드로 거른 공고만 가져온다.

mock 은 fixtures/bizinfo_mock.json. live 는 bizinfo.go.kr bizinfoApi.do (BIZINFO_API_KEY). 키 발급 후 필드 확인 필요.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from app.config import get_settings
from app.services.external.base import ConnectorUnavailable, http_get_json, load_fixture

SOURCE_CODE = "BIZINFO"
LIVE_URL = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"


@dataclass
class AnnouncementRecord:
    external_id: str
    title: str
    agency_name: str
    summary: str | None
    receipt_start: date | None
    receipt_end: date | None
    url: str | None
    raw: dict


def _period(v: str | None) -> tuple[date | None, date | None]:
    found = re.findall(r"(\d{4})[-.]?(\d{2})[-.]?(\d{2})", v or "")
    ds = [datetime(int(y), int(m), int(d)).date() for y, m, d in found]
    return (ds[0] if ds else None, ds[1] if len(ds) > 1 else None)


def _strip_tags(v: str | None) -> str | None:
    return re.sub(r"<[^>]+>", " ", v).strip() if v else None


def _record(it: dict) -> AnnouncementRecord:
    start, end = _period(it.get("reqstBeginEndDe"))
    return AnnouncementRecord(
        external_id=str(it.get("pblancId")), title=(it.get("pblancNm") or "").strip(),
        agency_name=(it.get("jrsdInsttNm") or it.get("excInsttNm") or "기업마당").strip(),
        summary=_strip_tags(it.get("bsnsSumryCn")), receipt_start=start, receipt_end=end,
        url=it.get("pblancUrl"), raw=it)


def matches_keywords(r: AnnouncementRecord, keywords: list[str]) -> bool:
    text = " ".join(x for x in (r.title, r.summary or "", str(r.raw.get("hashtags") or "")) if x)
    return not keywords or any(k in text for k in keywords)


class MockBizinfoConnector:
    mode = "mock"

    def __init__(self, items: list[dict]):
        self.items = items

    def announcements(self) -> list[AnnouncementRecord]:
        return [_record(it) for it in self.items]


class LiveBizinfoConnector:
    mode = "live"

    def __init__(self, key: str | None):
        if not key:
            raise ConnectorUnavailable("BIZINFO_API_KEY 없음")
        self.key = key

    def announcements(self) -> list[AnnouncementRecord]:
        body = http_get_json(LIVE_URL, {"crtfcKey": self.key, "dataType": "json", "searchCnt": 500})
        items = body.get("jsonArray") or body.get("items") or []
        return [_record(it) for it in items if it.get("pblancId")]


def get_bizinfo_connector() -> MockBizinfoConnector | LiveBizinfoConnector:
    s = get_settings()
    mode = s.source_bizinfo.lower()
    if mode == "mock":
        return MockBizinfoConnector(load_fixture("bizinfo_mock.json")["items"])
    if mode == "live":
        return LiveBizinfoConnector(s.bizinfo_api_key)
    raise ValueError(f"SOURCE_BIZINFO={mode} (mock|live)")
