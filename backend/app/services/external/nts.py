"""국세청 사업자 진위확인·상태조회.

VERIFIED: 번호·대표자명·개업일 일치 / FAILED: 등록부에 있으나 불일치(등록 거절) / UNVERIFIED: 확인 불가(미확인 저장)
mock 은 fixtures/nts_mock.json, live 는 공공데이터포털 api.odcloud.kr (NTS_SERVICE_KEY).
"""
import json
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from app.config import get_settings
from app.services.external.base import ConnectorUnavailable, http_post_json

SOURCE_CODE = "NTS_BIZ"
_STATUS = {"01": "ACTIVE", "02": "SUSPENDED", "03": "CLOSED"}
LIVE_BASE = "https://api.odcloud.kr/api/nts-businessman/v1"
STATUS_BATCH = 100   # 상태조회 1회 최대 사업자번호 수


def status_of(code: str | None) -> str:
    return _STATUS.get(code or "", "UNKNOWN")


@dataclass(frozen=True)
class BizVerifyResult:
    verify_status: Literal["VERIFIED", "UNVERIFIED", "FAILED"]
    business_status: Literal["ACTIVE", "SUSPENDED", "CLOSED", "UNKNOWN"]
    message: str
    raw: dict[str, Any] = field(default_factory=dict)


class MockNtsConnector:
    mode = "mock"

    def __init__(self, registry: dict[str, dict[str, str]]):
        self.registry = registry

    def verify(self, b_no: str, representative_name: str, opened_on: date) -> BizVerifyResult:
        start_dt = opened_on.strftime("%Y%m%d")
        req = {"b_no": b_no, "start_dt": start_dt, "p_nm": representative_name}
        rec = self.registry.get(b_no)
        if rec is None:
            raw = {"request_param": req, "valid": "02", "valid_msg": "확인할 수 없습니다."}
            return BizVerifyResult("UNVERIFIED", "UNKNOWN", "국세청 등록부에서 확인할 수 없어 미확인으로 저장합니다", raw)
        status = {"b_no": b_no, "b_stt_cd": rec["b_stt_cd"], "tax_type": rec.get("tax_type", "")}
        biz_status = _STATUS.get(rec["b_stt_cd"], "UNKNOWN")
        if rec["p_nm"].strip() == representative_name.strip() and rec["start_dt"] == start_dt:
            raw = {"request_param": req, "valid": "01", "status": status}
            return BizVerifyResult("VERIFIED", biz_status, "국세청 진위확인 통과", raw)
        raw = {"request_param": req, "valid": "02", "valid_msg": "확인할 수 없습니다."}
        return BizVerifyResult("FAILED", "UNKNOWN", "대표자명 또는 개업일이 국세청 등록 정보와 다릅니다", raw)


    def status(self, b_nos: list[str]) -> list[dict[str, Any]]:
        """상태조회 응답의 data 항목 모양. 등록부에 없으면 b_stt_cd 가 빈 값."""
        return [{"b_no": b, "b_stt_cd": self.registry.get(b, {}).get("b_stt_cd", ""),
                 "tax_type": self.registry.get(b, {}).get("tax_type", "")} for b in b_nos]


class LiveNtsConnector:
    mode = "live"

    def __init__(self, service_key: str | None):
        if not service_key:
            raise ConnectorUnavailable("NTS_SERVICE_KEY 없음")
        self.key = service_key

    def verify(self, b_no: str, representative_name: str, opened_on: date) -> BizVerifyResult:
        req = {"b_no": b_no, "start_dt": opened_on.strftime("%Y%m%d"), "p_nm": representative_name}
        body = http_post_json(f"{LIVE_BASE}/validate", {"businesses": [req]}, params={"serviceKey": self.key})
        item = (body.get("data") or [{}])[0]
        if item.get("valid") == "01":
            status = item.get("status") or {}
            return BizVerifyResult("VERIFIED", status_of(status.get("b_stt_cd")), "국세청 진위확인 통과", item)
        # 등록부에 번호가 있는지 상태조회로 구분 (있으면 불일치, 없으면 확인 불가)
        known = self.status([b_no])[0].get("b_stt_cd")
        if known:
            return BizVerifyResult("FAILED", "UNKNOWN", "대표자명 또는 개업일이 국세청 등록 정보와 다릅니다", item)
        return BizVerifyResult("UNVERIFIED", "UNKNOWN", "국세청 등록부에서 확인할 수 없어 미확인으로 저장합니다", item)

    def status(self, b_nos: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for i in range(0, len(b_nos), STATUS_BATCH):
            body = http_post_json(f"{LIVE_BASE}/status", {"b_no": b_nos[i:i + STATUS_BATCH]},
                                  params={"serviceKey": self.key})
            out.extend(body.get("data") or [])
        return out


@lru_cache
def _mock_registry() -> dict[str, dict[str, str]]:
    path = Path(__file__).parent / "fixtures" / "nts_mock.json"
    return json.loads(path.read_text(encoding="utf-8"))["businesses"]


def get_nts_connector() -> MockNtsConnector | LiveNtsConnector:
    mode = get_settings().source_nts_biz.lower()
    if mode == "mock":
        return MockNtsConnector(_mock_registry())
    if mode == "live":
        return LiveNtsConnector(get_settings().nts_service_key)
    raise ValueError(f"SOURCE_NTS_BIZ={mode} (mock|live)")
