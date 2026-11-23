-- 기업 상담용 가상 데이터 (navigator_companies.sql 다음에 실행)
--   D-STATE 보완 답변: 101 한빛(방산진입 준비), 102 누리(양산·공급망 고도화), 103 새봄(기초역량 정비)
-- 재실행 가능: psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f seeds/navigator_consult.sql
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL search_path = ax, public;

DELETE FROM company_dstate_value WHERE organization_id IN (101, 102, 103);

INSERT INTO company_dstate_value (organization_id, variable_code, origin, value) VALUES
  (101, 'TRL',               'SELF', '7'),
  (101, 'PROTOTYPE',         'SELF', '"HAVE"'),
  (101, 'RND_STAFF',         'SELF', '18'),
  (101, 'DQMS',              'SELF', '"NONE"'),
  (101, 'DEFENSE_HISTORY',   'SELF', '"NONE"'),
  (101, 'WEAPON_SYSTEM',     'SELF', '"CANDIDATE"'),
  (101, 'DEMAND',            'SELF', '"NONE"'),
  (101, 'TARGET_MARKET',     'SELF', '"NONE"'),
  (102, 'TRL',               'SELF', '8'),
  (102, 'PROTOTYPE',         'SELF', '"HAVE"'),
  (102, 'RND_STAFF',         'SELF', '40'),
  (102, 'WEAPON_SYSTEM',     'SELF', '"SPECIFIED"'),
  (102, 'DEMAND',            'SELF', '"CONFIRMED"'),
  (102, 'EXPORT_EXPERIENCE', 'SELF', '"DEFENSE"'),
  (102, 'TARGET_MARKET',     'SELF', '"CANDIDATE"'),
  (103, 'TRL',               'SELF', '4'),
  (103, 'PROTOTYPE',         'SELF', '"DEVELOPING"'),
  (103, 'RND_STAFF',         'SELF', '9');

COMMIT;
