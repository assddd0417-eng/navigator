-- 판정기준 설정, 진단 변수사전 관리, 상담 보완자료
--   review_criteria   공고문 점검 항목과 적합도 판정 기준 (역량 충족도 경계, 등급 경계, 부분 충족 비율). 버전으로 남긴다
--   dstate_variable   변수명·정의·증빙 원천·보완 질문을 화면에서 고친다 (산정식은 코드)
--   company_evidence  담당자가 상담 중 올린 보완자료 (uploaded_by, consultation_id)
SET search_path = ax, public;

CREATE TABLE ax.review_criteria (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    version     integer NOT NULL UNIQUE CHECK (version > 0),
    settings    jsonb NOT NULL,
    is_active   boolean NOT NULL DEFAULT false,
    note        text,
    created_by  bigint REFERENCES ax.app_user(id),
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX review_criteria_active ON ax.review_criteria ((true)) WHERE is_active;

COMMENT ON TABLE ax.review_criteria IS
    '공고문 점검 항목·판정 기준. 소관부서 협의로 정하고 모든 공고에 공통 적용. 바꾸면 새 버전';

INSERT INTO ax.review_criteria (version, settings, is_active, note) VALUES (1, '{
  "capability_full": 70, "capability_partial": 40, "grade_high": 70, "grade_mid": 50, "partial_ratio": 50,
  "check_items": [
    {"item": "신청자격", "content": "기업규모·소재지·업종, 방산 참여·진출 여부", "kind": "MANDATORY"},
    {"item": "신청제한", "content": "유사·중복 지원, 휴폐업·부도, 제재 이력", "kind": "MANDATORY"},
    {"item": "평가기준·배점", "content": "평가항목별 배점·세부지표", "kind": "FIT"},
    {"item": "우대·감점", "content": "지정·협약·인증 여부, 제재·포기 이력", "kind": "FIT"},
    {"item": "지원내용·기업부담", "content": "지원한도·기업부담 비율·지원기간", "kind": "GUIDE"},
    {"item": "제출서류", "content": "필수 서류·해당 시 제출 서류", "kind": "GUIDE"}
  ]}'::jsonb, true, '기본 기준');

CREATE TRIGGER trg_review_criteria_audit AFTER INSERT OR DELETE OR UPDATE ON ax.review_criteria
    FOR EACH ROW EXECUTE FUNCTION ax.audit_row('id');

ALTER TABLE ax.dstate_variable
    ADD COLUMN updated_at timestamptz,
    ADD COLUMN updated_by bigint REFERENCES ax.app_user(id);
CREATE TRIGGER trg_dstate_variable_audit AFTER UPDATE ON ax.dstate_variable
    FOR EACH ROW EXECUTE FUNCTION ax.audit_row('code');

ALTER TABLE ax.company_evidence
    ADD COLUMN uploaded_by bigint REFERENCES ax.app_user(id),
    ADD COLUMN consultation_id bigint REFERENCES ax.consultation(id) ON DELETE SET NULL,
    ADD COLUMN note text CHECK (length(note) <= 500);
COMMENT ON COLUMN ax.company_evidence.uploaded_by IS '담당자가 상담 중 올린 보완자료면 담당자. 기업이 올렸으면 NULL';
