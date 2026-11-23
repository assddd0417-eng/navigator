-- 기본 데이터: 기관 담당자 계정과 사업. 로컬 개발·API 스모크 테스트용.
--   사용자 ID (X-User-Id 헤더 값)
--     1 staff   STAFF   기관 담당자
--     2 viewer  (역할 없음)  권한 거부 확인용
--     3 owner   PROGRAM_OWNER 지원사업 소관부서
--     4 ax      AX_ADMIN      AX 주관부서
-- 재실행 안전: 고정 ID 로 UPSERT 하고, 시퀀스는 기존 최댓값 이상으로만 올린다.
-- backend/tests/conftest.py 의 SEED 와 같은 데이터다.
--   psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f seeds/base.sql
SET search_path = ax, public;

INSERT INTO department (id, dept_code, name) OVERRIDING SYSTEM VALUE VALUES
  (1, 'D-BIZ', '사업지원팀'), (2, 'D-PROG', '방산사업팀'), (3, 'D-AX', 'AX추진팀')
ON CONFLICT (id) DO UPDATE SET dept_code = EXCLUDED.dept_code, name = EXCLUDED.name;

INSERT INTO app_user (id, login_id, name, department_id, clearance_code) OVERRIDING SYSTEM VALUE VALUES
  (1, 'staff',  '공고담당', 1, 'INTERNAL'),
  (2, 'viewer', '열람자',   1, 'PUBLIC'),
  (3, 'owner',  '사업담당', 2, 'INTERNAL'),
  (4, 'ax',     'AX담당',   3, 'INTERNAL')
ON CONFLICT (id) DO UPDATE SET login_id = EXCLUDED.login_id, name = EXCLUDED.name,
                               department_id = EXCLUDED.department_id, clearance_code = EXCLUDED.clearance_code;

INSERT INTO user_role (user_id, role_code) VALUES (1, 'STAFF'), (3, 'PROGRAM_OWNER'), (4, 'AX_ADMIN')
ON CONFLICT DO NOTHING;

INSERT INTO program (id, program_code, name, program_type_code, purpose) OVERRIDING SYSTEM VALUE VALUES
  (1, 'P-LOC',  '부품국산화개발지원', 'PARTS_LOCALIZATION', '수입 부품의 국산화로 공급망 안정'),
  (2, 'P-CORE', '핵심기술개발',       'CORE_TECH',          '미래 핵심기술 확보')
ON CONFLICT (id) DO UPDATE SET program_code = EXCLUDED.program_code, name = EXCLUDED.name,
                               program_type_code = EXCLUDED.program_type_code, purpose = EXCLUDED.purpose;

SELECT setval(pg_get_serial_sequence('ax.department', 'id'), GREATEST(10, (SELECT max(id) FROM department)));
SELECT setval(pg_get_serial_sequence('ax.app_user', 'id'), GREATEST(10, (SELECT max(id) FROM app_user)));
SELECT setval(pg_get_serial_sequence('ax.organization', 'id'), GREATEST(10, (SELECT max(id) FROM organization)));
SELECT setval(pg_get_serial_sequence('ax.program', 'id'), GREATEST(10, (SELECT max(id) FROM program)));
