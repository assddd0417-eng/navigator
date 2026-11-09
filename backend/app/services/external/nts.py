"""국세청 사업자등록정보 진위확인·상태조회 (공공데이터포털) 연결 부품.

진위확인은 사업자번호·대표자명·개업일이 모두 맞아야 통과한다.
- VERIFIED   세 값이 일치 (화면: 확인됨)
- FAILED     등록부에 있으나 대표자명·개업일 불일치 → 등록 거절 (남의 사업자번호로 만든 거짓 프로필 방지)
- UNVERIFIED 확인할 수 없음(등록부에 없음·연결 불가) → 저장하되 '미확인' 표시

SOURCE_NTS_BIZ=mock (기본): fixtures/nts_mock.json 의 가상 등록부로 응답한다. 응답 모양은 실제 API 를 흉내 낸다.
SOURCE_NTS_BIZ=live: 6단계(외부 자동수집)에서 실제 호출을 붙인다. 지금은 ConnectorUnavailable → 미확인.
"""
import json
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from app.config import get_settings
from app.services.external.base import ConnectorUnavailable

SOURCE_CODE = "NTS_BIZ"
_STATUS = {"01": "ACTIVE", "02": "SUSPENDED", "03": "CLOSED"}


@dataclass(frozen=True)
class BizVerifyResult:
    verify_status: Literal["VERIFIED", "UNVERIFIED", "FAILED"]
    business_status: Literal["ACTIVE", "SUSPENDED", "CLOSED", "UNKNOWN"]
    message: str
    raw: dict[str, Any] = field(default_factory=dict)   # 받은 원본 (external_raw_record.payload)


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


class LiveNtsConnector:
    mode = "live"

    def verify(self, b_no: str, representative_name: str, opened_on: date) -> BizVerifyResult:
        raise ConnectorUnavailable("국세청 실제 연결은 6단계(외부 자동수집)에서 붙입니다")


@lru_cache
def _mock_registry() -> dict[str, dict[str, str]]:
    path = Path(__file__).parent / "fixtures" / "nts_mock.json"
    return json.loads(path.read_text(encoding="utf-8"))["businesses"]


def get_nts_connector() -> MockNtsConnector | LiveNtsConnector:
    mode = get_settings().source_nts_biz.lower()
    if mode == "mock":
        return MockNtsConnector(_mock_registry())
    if mode == "live":
        return LiveNtsConnector()
    raise ValueError(f"SOURCE_NTS_BIZ={mode} (mock|live)")
