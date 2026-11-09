"""외부 데이터 연결 부품.

출처마다 연결 부품 하나를 두고, 설정 한 줄(SOURCE_<CODE>=mock|live)로 목업과 실제를 바꾼다.
받은 원본은 external_raw_record 에 그대로 저장하고(record_fetch), 우리 테이블 모양으로 바꿔 넣는다.
그래서 실제 API 로 바꿔도 호출부(라우터·매칭·화면)는 그대로다.

1단계: 국세청 사업자 진위확인·상태조회(NTS_BIZ) 목업만. 나머지 출처는 6단계에서 추가한다.
"""
from app.services.external.base import ConnectorUnavailable, record_fetch
from app.services.external.nts import BizVerifyResult, get_nts_connector

__all__ = ["BizVerifyResult", "ConnectorUnavailable", "get_nts_connector", "record_fetch"]
