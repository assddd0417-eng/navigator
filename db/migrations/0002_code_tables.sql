-- =============================================================================
-- 0002: 코드 테이블 (업무 분류 코드)
--   업무 코드는 PostgreSQL ENUM 대신 코드 테이블로 관리한다.
--   - 한글 명칭·설명·정렬순서·사용여부 등 메타데이터를 함께 보관
--   - 운영 중 코드 추가/비활성화가 DDL 없이 가능
--   - FK 로 무결성 보장
--   시스템 내부 상태값(검토 상태 등)은 각 테이블의 CHECK 제약으로 관리한다.
-- =============================================================================
SET search_path = ax, public;

-- ---------------------------------------------------------------------------
-- 6대 연계 유형
-- ---------------------------------------------------------------------------
CREATE TABLE ax.code_linkage_type (
    code              text PRIMARY KEY,
    name_ko           text    NOT NULL UNIQUE,
    description       text    NOT NULL,
    min_source_cards  smallint NOT NULL DEFAULT 1 CHECK (min_source_cards >= 1), -- 융합형은 2
    requires_company  boolean NOT NULL DEFAULT false,                           -- 사업화형: 기업/품목 후보 필요
    sort_order        smallint NOT NULL,
    is_active         boolean NOT NULL DEFAULT true
);
COMMENT ON TABLE ax.code_linkage_type IS '이어달리기 6대 연계 유형';

INSERT INTO ax.code_linkage_type (code, name_ko, description, min_source_cards, requires_company, sort_order) VALUES
 ('FOLLOW_UP',         '후속형',   '기존 과제의 미해결 기술을 이어서 개발',               1, false, 1),
 ('ADVANCEMENT',       '고도화형', '기존 성능을 향상하거나 적용환경 확대',                 1, false, 2),
 ('TRANSITION',        '전환형',   '다른 무기체계·부품·사업트랙에 적용',                   1, false, 3),
 ('CONVERGENCE',       '융합형',   '두 개 이상 기존 성과를 결합하여 신규기술 구성',        2, false, 4),
 ('UTILIZATION',       '활용형',   '기존 성과를 별도 개발 없이 시험·실증·적용',            1, false, 5),
 ('COMMERCIALIZATION', '사업화형', '기업·품목·수출사업으로 연계 검토',                     1, true,  6);

-- ---------------------------------------------------------------------------
-- 공통 형태의 코드 테이블
-- ---------------------------------------------------------------------------
CREATE TABLE ax.code_program_type (
    code text PRIMARY KEY, name_ko text NOT NULL UNIQUE, description text,
    sort_order smallint NOT NULL DEFAULT 0, is_active boolean NOT NULL DEFAULT true
);
COMMENT ON TABLE ax.code_program_type IS '사업 유형 (부품국산화·벤처·민군·핵심기술·신속시범·수출지원 등)';
INSERT INTO ax.code_program_type (code, name_ko, sort_order) VALUES
 ('PARTS_LOCALIZATION', '부품국산화', 1),
 ('DEFENSE_VENTURE',    '국방벤처',   2),
 ('CIVIL_MILITARY',     '민군기술협력', 3),
 ('CORE_TECH',          '핵심기술',   4),
 ('RAPID_PILOT',        '신속시범',   5),
 ('EXPORT_SUPPORT',     '수출지원',   6),
 ('OTHER',              '기타',      99);

CREATE TABLE ax.code_project_status (
    code text PRIMARY KEY, name_ko text NOT NULL UNIQUE, description text,
    sort_order smallint NOT NULL DEFAULT 0, is_active boolean NOT NULL DEFAULT true
);
INSERT INTO ax.code_project_status (code, name_ko, sort_order) VALUES
 ('PLANNING', '기획', 1), ('IN_PROGRESS', '진행', 2), ('COMPLETED', '종료', 3),
 ('SUSPENDED', '중단', 4), ('CANCELLED', '취소', 5);

CREATE TABLE ax.code_dev_stage (
    code text PRIMARY KEY, name_ko text NOT NULL UNIQUE, description text,
    stage_rank smallint NOT NULL,                      -- 단계 비교(적합도 계산)용 순서
    sort_order smallint NOT NULL DEFAULT 0, is_active boolean NOT NULL DEFAULT true
);
COMMENT ON TABLE ax.code_dev_stage IS '연구개발 단계 (TRL 과 별도로 관리)';
INSERT INTO ax.code_dev_stage (code, name_ko, stage_rank, sort_order) VALUES
 ('BASIC',        '기초연구',   1, 1),
 ('APPLIED',      '응용연구',   2, 2),
 ('PROTOTYPE',    '시제품개발', 3, 3),
 ('SYSTEM_DEV',   '체계개발',   4, 4),
 ('PILOT',        '시험·실증',  5, 5),
 ('MASS_PROD',    '양산',      6, 6);

CREATE TABLE ax.code_security_level (
    code text PRIMARY KEY, name_ko text NOT NULL UNIQUE, description text,
    level_rank smallint NOT NULL UNIQUE,               -- 숫자가 클수록 높은 등급
    sort_order smallint NOT NULL DEFAULT 0, is_active boolean NOT NULL DEFAULT true
);
COMMENT ON TABLE ax.code_security_level IS '보안등급. 실제 등급 체계는 원천시스템 기준으로 교체(가정값)';
INSERT INTO ax.code_security_level (code, name_ko, level_rank, sort_order) VALUES
 ('PUBLIC',     '공개',   0, 1),
 ('INTERNAL',   '내부',   1, 2),
 ('RESTRICTED', '대외비', 2, 3),
 ('CLASSIFIED', '비밀',   3, 4);

CREATE TABLE ax.code_document_type (
    code text PRIMARY KEY, name_ko text NOT NULL UNIQUE, description text,
    sort_order smallint NOT NULL DEFAULT 0, is_active boolean NOT NULL DEFAULT true
);
INSERT INTO ax.code_document_type (code, name_ko, sort_order) VALUES
 ('RND_PLAN',       '연구개발계획서', 1),
 ('FINAL_REPORT',   '결과보고서',     2),
 ('PAPER',          '논문',          3),
 ('PATENT',         '특허·지재권',    4),
 ('ACQUIRED_TECH',  '획득기술자료',   5),
 ('TEST_REPORT',    '시험성적서',     6),
 ('EVALUATION',     '평가자료',      7),
 ('PROGRAM_NOTICE', '사업공고·시행계획', 8),
 ('PROGRAM_RULE',   '사업규정',      9),
 ('DEMAND_DOC',     '기획수요자료',  10),
 ('MEETING_MINUTES','회의자료',      11),
 ('OTHER',          '기타',         99);

CREATE TABLE ax.code_outcome_type (
    code text PRIMARY KEY, name_ko text NOT NULL UNIQUE, description text,
    sort_order smallint NOT NULL DEFAULT 0, is_active boolean NOT NULL DEFAULT true
);
COMMENT ON TABLE ax.code_outcome_type IS '주요 연구성과·지식재산권 유형';
INSERT INTO ax.code_outcome_type (code, name_ko, sort_order) VALUES
 ('PAPER', '논문', 1), ('PATENT_APPLIED', '특허출원', 2), ('PATENT_REGISTERED', '특허등록', 3),
 ('SOFTWARE', '소프트웨어', 4), ('TECH_TRANSFER', '기술이전', 5), ('PROTOTYPE', '시제품', 6),
 ('TEST_RESULT', '시험성과', 7), ('STANDARD', '표준·규격', 8), ('OTHER', '기타', 99);

CREATE TABLE ax.code_source_system (
    code text PRIMARY KEY, name_ko text NOT NULL UNIQUE, description text,
    sort_order smallint NOT NULL DEFAULT 0, is_active boolean NOT NULL DEFAULT true
);
COMMENT ON TABLE ax.code_source_system IS '원천 정보시스템';
INSERT INTO ax.code_source_system (code, name_ko, sort_order) VALUES
 ('PMS',    '과제관리시스템(PMS)',  1),
 ('DTIMS',  'DTiMS',              2),
 ('DSIS',   '방위산업정보시스템',    3),
 ('MANUAL', '수기입력',            8),
 ('AX',     'AX 플랫폼 생성',       9);

CREATE TABLE ax.code_review_decision (
    code text PRIMARY KEY, name_ko text NOT NULL UNIQUE, description text,
    is_terminal boolean NOT NULL DEFAULT true,         -- 최종판정 가능 여부
    sort_order smallint NOT NULL DEFAULT 0, is_active boolean NOT NULL DEFAULT true
);
COMMENT ON TABLE ax.code_review_decision IS 'Human-in-the-Loop 판정 코드';
INSERT INTO ax.code_review_decision (code, name_ko, is_terminal, sort_order) VALUES
 ('ADOPT',      '채택',          true,  1),
 ('HOLD',       '보류',          true,  2),
 ('EXCLUDE',    '제외',          true,  3),
 ('NEEDS_INFO', '추가 확인 필요', false, 4);
