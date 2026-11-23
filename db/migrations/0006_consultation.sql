-- 상담 요청·상담 이력·상담결과서
--   consult_request  기업이 관리 링크로 남긴 상담 요청 (애로사항, 관심 지원사업)
--   consultation     담당자 상담 실행 결과 스냅샷(진단·판정·경로)과 상담결과서 초안, 담당자 수정·확정
SET search_path = ax, public;

CREATE TABLE ax.consult_request (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id  bigint NOT NULL REFERENCES ax.organization(id) ON DELETE CASCADE,
    concern          text NOT NULL CHECK (length(concern) BETWEEN 1 AND 2000),
    interest         text CHECK (length(interest) <= 500),
    contact_name     text CHECK (length(contact_name) <= 100),
    contact_phone    text CHECK (length(contact_phone) <= 40),
    status           text NOT NULL DEFAULT 'REQUESTED' CHECK (status IN ('REQUESTED', 'IN_PROGRESS', 'DONE', 'CANCELED')),
    origin           text NOT NULL DEFAULT 'SELF' CHECK (origin IN ('SELF', 'STAFF')),
    handled_by       bigint REFERENCES ax.app_user(id),
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX consult_request_open ON ax.consult_request (status, created_at DESC);
CREATE INDEX consult_request_org ON ax.consult_request (organization_id, created_at DESC);

COMMENT ON TABLE ax.consult_request IS '상담 요청. 기업이 관리 링크로 남기거나 담당자가 대신 등록';

CREATE TABLE ax.consultation (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id  bigint NOT NULL REFERENCES ax.organization(id) ON DELETE CASCADE,
    request_id       bigint REFERENCES ax.consult_request(id) ON DELETE SET NULL,
    task             text NOT NULL CHECK (task IN ('A', 'B', 'C')),
    concern          text,
    diagnosis_id     bigint REFERENCES ax.company_diagnosis(id) ON DELETE SET NULL,
    diagnosis        jsonb NOT NULL,
    eligibility      jsonb,
    route            jsonb,
    draft            jsonb NOT NULL CHECK (jsonb_typeof(draft) = 'array'),
    report           jsonb NOT NULL CHECK (jsonb_typeof(report) = 'array'),
    overrides        jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(overrides) = 'array'),
    feedback         text,
    status           text NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'CONFIRMED')),
    shared_at        timestamptz,
    notified_at      timestamptz,
    created_by       bigint REFERENCES ax.app_user(id),
    confirmed_by     bigint REFERENCES ax.app_user(id),
    confirmed_at     timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CHECK (status = 'DRAFT' OR confirmed_at IS NOT NULL)
);
CREATE INDEX consultation_org ON ax.consultation (organization_id, created_at DESC);

COMMENT ON TABLE ax.consultation IS
    '상담 이력. draft 는 처음 만든 상담결과서 초안(고치지 않음), report 는 담당자가 고친 본. overrides 는 판정 수정 [{announcement_id, verdict, reason}]';

CREATE TRIGGER trg_consult_request_audit AFTER INSERT OR DELETE OR UPDATE ON ax.consult_request
    FOR EACH ROW EXECUTE FUNCTION ax.audit_row('id');
CREATE TRIGGER trg_consultation_audit AFTER INSERT OR DELETE OR UPDATE ON ax.consultation
    FOR EACH ROW EXECUTE FUNCTION ax.audit_row('id');
