-- 0025: Navigator 외부 수집
--   BIZINFO 공고 출처 추가, 국세청 상태 재확인 주기
--   company_external_id  출처별 기업 식별자 (DART 고유번호, KIPRIS 특허고객번호)
SET search_path = ax, public;

INSERT INTO ax.external_source (code, name, provider, method, data_kind, fetch_interval, requires_key, is_paid, notes)
VALUES ('BIZINFO', '기업마당 지원사업 공고', '중소벤처기업부 (기업마당)', 'API', 'ANNOUNCEMENT', '1 day', true, false,
        '키워드로 거른 공고를 작성중으로 넣고 담당자가 요건 입력 후 공개')
ON CONFLICT (code) DO NOTHING;

UPDATE ax.external_source SET fetch_interval = '30 days', notes = '등록 시 진위확인 + 30일마다 휴·폐업 재확인. 무료'
 WHERE code = 'NTS_BIZ';

CREATE TABLE ax.company_external_id (
    organization_id  bigint NOT NULL REFERENCES ax.organization(id) ON DELETE CASCADE,
    source_id        bigint NOT NULL REFERENCES ax.external_source(id),
    external_id      text NOT NULL,
    set_by           text NOT NULL DEFAULT 'COLLECTOR' CHECK (set_by IN ('COLLECTOR','STAFF')),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, source_id)
);
CREATE TRIGGER trg_company_external_id_audit AFTER INSERT OR UPDATE OR DELETE ON ax.company_external_id
    FOR EACH ROW EXECUTE FUNCTION ax.audit_row('organization_id', 'source_id');
