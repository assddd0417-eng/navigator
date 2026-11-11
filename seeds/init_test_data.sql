-- =============================================================================
-- 최소 시드: API 스모크 테스트(scripts/smoke_test.sh)와 로컬 개발용 기준 데이터
--   부서 3 · 사용자 6(역할 포함) · 부서 열람권 1 · 기관 2 · 사업 2 · 무기체계 2 · 품목 1 · 과제 3
--
--   사용자 ID (X-User-Id 헤더 값)
--     1 planner   PLANNER        과제기획팀
--     2 reviewer  DEPT_REVIEWER  무인미래통신기술팀  ← 과제 1(항재밍 데이터링크)의 소관부서
--     3 expert    EXPERT         지휘정찰기술팀
--     4 curator   CURATOR        과제기획팀
--     5 viewer    VIEWER         지휘정찰기술팀      (권한 거부 확인용)
--     6 agency    VIEWER         과제기획팀          (기관 포트폴리오 조회 전용 시연, 대외비까지 열람)
--
-- 전제: db/migrations 0001~0015 적용 (코드 테이블·역할 마스터는 마이그레이션이 넣는다).
-- 재실행 안전: 모든 행을 고정 ID 로 UPSERT 하고, 시퀀스는 기존 최댓값 이상으로만 올린다.
-- backend/tests/conftest.py 의 SEED 와 같은 데이터다 (한쪽을 바꾸면 다른 쪽도 맞출 것).
--
--   psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f seeds/init_test_data.sql
-- =============================================================================
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL search_path = ax, public;

-- 부서
INSERT INTO department (id, dept_code, name, description) OVERRIDING SYSTEM VALUE VALUES
  (1, 'D-PLAN', '과제기획팀',         '신규 과제 기획·사업 관리'),
  (2, 'D-C4I',  '지휘정찰기술팀',     '지휘통제·정찰·영상 처리'),
  (3, 'D-COMM', '무인미래통신기술팀', '무인체계 데이터링크·전술통신')
ON CONFLICT (id) DO UPDATE SET dept_code = EXCLUDED.dept_code, name = EXCLUDED.name,
                               description = EXCLUDED.description, is_active = true;

-- 사용자 (clearance_code → code_security_level, department_id → department)
INSERT INTO app_user (id, login_id, name, department_id, clearance_code) OVERRIDING SYSTEM VALUE VALUES
  (1, 'planner',  '기획담당',   1, 'RESTRICTED'),
  (2, 'reviewer', '부서검토자', 3, 'RESTRICTED'),
  (3, 'expert',   '기술전문가', 2, 'RESTRICTED'),
  (4, 'curator',  '카드관리자', 1, 'RESTRICTED'),
  (5, 'viewer',   '열람자',     2, 'PUBLIC'),
  (6, 'agency',   '정책기획 열람자', 1, 'RESTRICTED')
ON CONFLICT (id) DO UPDATE SET login_id = EXCLUDED.login_id, name = EXCLUDED.name,
                               department_id = EXCLUDED.department_id,
                               clearance_code = EXCLUDED.clearance_code, is_active = true;

-- 역할 (role_code → app_role, 0003 에서 생성)
INSERT INTO user_role (user_id, role_code) VALUES
  (1, 'PLANNER'), (2, 'DEPT_REVIEWER'), (3, 'EXPERT'), (4, 'CURATOR'), (5, 'VIEWER'), (6, 'VIEWER')
ON CONFLICT (user_id, role_code) DO NOTHING;

-- 기획팀(1)은 통신팀(3) 소관 자료를 RESTRICTED 까지 열람 가능 → 큐레이터·기획자가 원문 근거를 볼 수 있다.
-- 전문가(지휘정찰팀)는 열람권이 없어 추천 상세에서 근거 원문이 가려진다.
INSERT INTO department_access_grant (grantee_dept_id, target_dept_id, max_security_code)
SELECT 1, 3, 'RESTRICTED'
WHERE NOT EXISTS (SELECT 1 FROM department_access_grant
                   WHERE grantee_dept_id = 1 AND target_dept_id = 3 AND grantee_user_id IS NULL);

-- 기관
INSERT INTO organization (id, name, org_type) OVERRIDING SYSTEM VALUE VALUES
  (1, '(주)테스트방산',   'COMPANY'),
  (2, '국방기술연구원',   'RESEARCH_INSTITUTE')
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, org_type = EXCLUDED.org_type, is_active = true;

-- 사업 (program_type_code → code_program_type, owner_dept_id → department)
INSERT INTO program (id, program_code, name, program_type_code, purpose, owner_dept_id) OVERRIDING SYSTEM VALUE VALUES
  (1, 'P-LOC',  '부품국산화개발지원', 'PARTS_LOCALIZATION', '수입 부품의 국산화로 공급망 안정', 1),
  (2, 'P-CORE', '핵심기술개발',       'CORE_TECH',          '미래 핵심기술 확보',               1)
ON CONFLICT (id) DO UPDATE SET program_code = EXCLUDED.program_code, name = EXCLUDED.name,
                               program_type_code = EXCLUDED.program_type_code,
                               purpose = EXCLUDED.purpose, owner_dept_id = EXCLUDED.owner_dept_id;

-- 무기체계·품목 (카드/수요의 weapon_systems, 사업화형 품목 후보에서 참조)
INSERT INTO weapon_system (id, system_code, name) OVERRIDING SYSTEM VALUE VALUES
  (1, 'WS-001', '소형전술드론'),
  (2, 'WS-002', '차륜형장갑차')
ON CONFLICT (id) DO UPDATE SET system_code = EXCLUDED.system_code, name = EXCLUDED.name;

INSERT INTO item (id, item_no, name, is_part, is_imported) OVERRIDING SYSTEM VALUE VALUES
  (1, 'ITM-0001', '항재밍 데이터링크 모뎀', true, true)
ON CONFLICT (id) DO UPDATE SET item_no = EXCLUDED.item_no, name = EXCLUDED.name,
                               is_part = EXCLUDED.is_part, is_imported = EXCLUDED.is_imported;

-- 과제 (program_id → program, lead_org_id → organization, department_id → department = 소관부서)
INSERT INTO project (id, project_no, title, program_id, lead_org_id, department_id, status_code, end_date)
OVERRIDING SYSTEM VALUE VALUES
  (1, 'PRJ-2022-001', '소형 무인기용 항재밍 데이터링크 개발', 2, 2, 3, 'COMPLETED', '2024-12-31'),
  (2, 'PRJ-2021-007', '전술 배터리 열관리 기술',             2, 2, 2, 'COMPLETED', '2023-06-30'),
  (3, 'PRJ-2023-004', 'EO/IR 영상 기반 표적 자동탐지',       2, 2, 2, 'COMPLETED', '2025-06-30')
ON CONFLICT (id) DO UPDATE SET project_no = EXCLUDED.project_no, title = EXCLUDED.title,
                               program_id = EXCLUDED.program_id, lead_org_id = EXCLUDED.lead_org_id,
                               department_id = EXCLUDED.department_id, status_code = EXCLUDED.status_code,
                               end_date = EXCLUDED.end_date;

-- 고정 ID 로 넣었으므로 시퀀스를 앞으로 당겨 이후 API 가 만드는 행과 충돌하지 않게 한다 (줄이지는 않음)
DO $$
DECLARE t text; m bigint;
BEGIN
  FOREACH t IN ARRAY ARRAY['department','app_user','organization','program','weapon_system','item','project'] LOOP
    EXECUTE format('SELECT COALESCE(max(id), 0) FROM ax.%I', t) INTO m;
    PERFORM setval(pg_get_serial_sequence('ax.' || t, 'id'), GREATEST(m, 10));
  END LOOP;
END $$;

COMMIT;

-- 확인용 요약
SELECT u.id AS user_id, u.login_id, string_agg(r.role_code, ',') AS roles, d.name AS department
  FROM ax.app_user u JOIN ax.department d ON d.id = u.department_id
  LEFT JOIN ax.user_role r ON r.user_id = u.id
 WHERE u.id BETWEEN 1 AND 6
 GROUP BY u.id, u.login_id, d.name ORDER BY u.id;
