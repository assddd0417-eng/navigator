-- 성장경로 서비스 역할과 기업정보 열람 권한
--   역할: STAFF 기업지원 담당자, PROGRAM_OWNER 지원사업 소관부서, AX_ADMIN AX 주관부서
--   company_access: 기업정보를 볼 수 있는 부서. 행이 없으면 모든 담당 부서가 본다
SET search_path = ax, public;

UPDATE ax.app_role SET name_ko = '기업지원 담당자',
       description = '기업 상담: 성장준비도 진단, 자격요건 검토, 성장경로 추천, 결과 확정·안내'
 WHERE code = 'STAFF';

INSERT INTO ax.app_role (code, name_ko, description) VALUES
  ('PROGRAM_OWNER', '지원사업 소관부서', '공고·운영규정 등록, 예외 요건 보정, 판단기준·사업 연계관계 관리'),
  ('AX_ADMIN',      'AX 주관부서',       '상담이력 점검·기준 보정, 진단 변수사전·판정기준 반영, 기업정보 열람 권한 관리')
ON CONFLICT (code) DO NOTHING;

CREATE TABLE ax.company_access (
    organization_id  bigint NOT NULL REFERENCES ax.organization(id) ON DELETE CASCADE,
    department_id    bigint NOT NULL REFERENCES ax.department(id) ON DELETE CASCADE,
    created_by       bigint REFERENCES ax.app_user(id),
    created_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, department_id)
);

COMMENT ON TABLE ax.company_access IS
    '기업정보 열람 부서. 기업에 행이 하나라도 있으면 그 부서와 AX 주관부서만 상담·조회할 수 있다';

CREATE TRIGGER trg_company_access_audit AFTER INSERT OR DELETE OR UPDATE ON ax.company_access
    FOR EACH ROW EXECUTE FUNCTION ax.audit_row('organization_id', 'department_id');
