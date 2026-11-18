-- 시연·시험 데이터를 비우고 실데이터를 넣을 준비를 한다.
--   지우는 것: 기업 전체, 공고 전체(첨부·원문 포함), 매칭·추천·알림·권유 기록, 외부 수집 기록, 검증 기록,
--             이름에 '(가상)' 이 붙은 사업
--   남기는 것: 기관 담당자 계정, 코드표, 사업(가상 제외), 외부 출처 설정, 임베딩 모델, 감사 로그
--   2번 열람자 계정(권한 거부 확인용)은 끈다.
-- 실데이터를 넣은 뒤에는 실행하지 않는다. 실수 방지로 confirm 변수가 있어야 돈다.
--   psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -v confirm=yes -f scripts/clear_demo_data.sql
\set ON_ERROR_STOP on
\if :{?confirm}
\else
  \echo '기업·공고 데이터를 모두 지웁니다. 실행하려면 -v confirm=yes 를 붙이세요.'
  \quit
\endif

BEGIN;
SET LOCAL search_path = ax, public;

SELECT 'before' AS at,
       (SELECT count(*) FROM organization WHERE org_type = 'COMPANY') AS companies,
       (SELECT count(*) FROM announcement) AS announcements,
       (SELECT count(*) FROM company_match_run) AS match_runs;

DELETE FROM company_match_run;          -- 추천·판정·근거는 CASCADE
DELETE FROM announcement;               -- 요건·요구기술·첨부·벡터·알림·권유는 CASCADE
DELETE FROM source_document;            -- 공고문 원문·청크·근거
DELETE FROM organization WHERE org_type = 'COMPANY';   -- 프로필·인증·특허·증빙·구독·관리 링크는 CASCADE
DELETE FROM external_fetch_job;         -- 수집 원본은 CASCADE
DELETE FROM eval_run;
DELETE FROM program WHERE name LIKE '%(가상)%';
UPDATE app_user SET is_active = false WHERE id = 2 AND login_id = 'viewer';

SELECT 'after' AS at,
       (SELECT count(*) FROM organization WHERE org_type = 'COMPANY') AS companies,
       (SELECT count(*) FROM announcement) AS announcements,
       (SELECT count(*) FROM company_match_run) AS match_runs;
COMMIT;
