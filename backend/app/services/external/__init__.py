"""외부 출처 커넥터. SOURCE_<CODE>=mock|live 로 전환, 원본은 external_raw_record 에 저장."""
from app.services.external.base import ConnectorUnavailable, record_fetch
from app.services.external.nts import BizVerifyResult, get_nts_connector

__all__ = ["BizVerifyResult", "ConnectorUnavailable", "get_nts_connector", "record_fetch"]
