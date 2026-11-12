-- Navigator 테스트 기업 3곳 (사업자번호 999- 는 가상)
--   101 한빛전자통신 999-81-00015  통신   대전 SME      NTS 확인
--   102 누리복합소재 999-82-00026  복합재 경남 MIDSIZE  NTS 확인, 방산업체, 매출 자가입력≠DART
--   103 새봄비전AI   999-83-00038  영상AI 경기 STARTUP  미확인, R&D 이력 없음
-- 관리 링크는 넣지 않음 (POST /navigator/companies/{brn}/access-link).
-- 재실행 가능: psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f seeds/navigator_companies.sql
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL search_path = ax, public;

INSERT INTO organization (id, name, org_type, business_reg_no) OVERRIDING SYSTEM VALUE VALUES
  (101, '(가상)한빛전자통신', 'COMPANY', '9998100015'),
  (102, '(가상)누리복합소재', 'COMPANY', '9998200026'),
  (103, '(가상)새봄비전AI',   'COMPANY', '9998300038')
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, org_type = EXCLUDED.org_type,
                               business_reg_no = EXCLUDED.business_reg_no, is_active = true;

INSERT INTO company_profile (organization_id, is_defense_company, company_size, main_business, homepage,
                             representative_name, opened_on, established_on, employee_count, annual_revenue_krw,
                             revenue_year, region, address, business_status, business_status_checked_at,
                             biz_verify_status, biz_verified_at, registered_email, registration_channel) VALUES
  (101, false, 'SME', '전술 데이터링크 모뎀, 소형 무인기용 항재밍 통신 장비, 메시 네트워크 무전기 개발·생산',
   'https://hanbit.example', '김한빛', '2012-03-15', '2012-03-15', 85, 18200000000, 2025, '대전',
   '대전광역시 유성구 (가상 주소)', 'ACTIVE', now(), 'VERIFIED', now(), 'contact@hanbit.example', 'SELF'),
  (102, true, 'MIDSIZE', '탄소섬유·세라믹 복합 방탄판, 항공기 경량 복합재 구조물, 열가소성 복합재 성형',
   'https://nuri.example', '이누리', '2005-09-02', '2005-09-02', 320, 124000000000, 2025, '경남',
   '경상남도 창원시 성산구 (가상 주소)', 'ACTIVE', now(), 'VERIFIED', now(), 'rnd@nuri.example', 'SELF'),
  (103, false, 'STARTUP', 'EO/IR 영상 기반 표적 자동탐지·추적 AI 소프트웨어, 경량 추론 모듈',
   'https://saebom.example', '박새봄', '2021-06-01', '2021-06-01', 14, 900000000, 2025, '경기',
   '경기도 성남시 분당구 (가상 주소)', 'UNKNOWN', NULL, 'UNVERIFIED', NULL, 'hello@saebom.example', 'SELF')
ON CONFLICT (organization_id) DO UPDATE SET
  is_defense_company = EXCLUDED.is_defense_company, company_size = EXCLUDED.company_size,
  main_business = EXCLUDED.main_business, homepage = EXCLUDED.homepage,
  representative_name = EXCLUDED.representative_name, opened_on = EXCLUDED.opened_on,
  established_on = EXCLUDED.established_on, employee_count = EXCLUDED.employee_count,
  annual_revenue_krw = EXCLUDED.annual_revenue_krw, revenue_year = EXCLUDED.revenue_year,
  region = EXCLUDED.region, address = EXCLUDED.address, business_status = EXCLUDED.business_status,
  business_status_checked_at = EXCLUDED.business_status_checked_at,
  biz_verify_status = EXCLUDED.biz_verify_status, biz_verified_at = EXCLUDED.biz_verified_at,
  registered_email = EXCLUDED.registered_email, registration_channel = EXCLUDED.registration_channel;

-- 결격사유·실적 (0027)
UPDATE company_profile SET tax_delinquent = false, insolvent = false, rnd_restricted = false,
       defense_goods = false, military_supply_krw = 0, export_krw = 1200000000, export_year = 2025 WHERE organization_id = 101;
UPDATE company_profile SET tax_delinquent = false, insolvent = false, rnd_restricted = false,
       defense_goods = true, military_supply_krw = 8700000000, export_krw = 3400000000, export_year = 2025 WHERE organization_id = 102;
-- 103 새봄비전AI 는 비워 둠 (화면에서 '확인 필요' 흐름 시연)

-- 초기화
DELETE FROM company_patent        WHERE organization_id IN (101,102,103);
DELETE FROM company_certification WHERE organization_id IN (101,102,103);
DELETE FROM company_credit_rating WHERE organization_id IN (101,102,103);
DELETE FROM company_rnd_history   WHERE organization_id IN (101,102,103);
DELETE FROM company_field_source  WHERE organization_id IN (101,102,103);
DELETE FROM company_access_link   WHERE organization_id IN (101,102,103);

-- 특허
INSERT INTO company_patent (organization_id, application_no, registration_no, title, abstract, ipc_codes, status,
                            applied_on, registered_on, origin, verified_at) VALUES
  (101, '10-2019-0101501', '10-2234501', '광대역 재밍 환경에서의 주파수 도약 동기 유지 장치 및 방법',
   '재밍 신호를 감지하면 도약 패턴과 동기 프레임을 적응적으로 바꿔 동기 유지 시간을 늘린다',
   '{H04B 1/713,H04K 3/00}', 'REGISTERED', '2019-08-20', '2021-03-11', 'SELF', NULL),
  (101, '10-2023-0055120', NULL, '소형 무인기 군집용 저지연 메시 네트워크 라우팅 방법',
   '노드 이동성을 예측해 경로를 미리 바꿔 지연을 줄인다', '{H04W 40/18,H04W 84/18}', 'APPLIED',
   '2023-05-02', NULL, 'SELF', NULL),
  (102, '10-2016-0144210', '10-1872210', '탄소섬유와 세라믹 타일을 적층한 경량 복합 방탄판',
   '세라믹 타일 뒤에 탄소섬유 적층을 두어 같은 방호 등급에서 무게를 줄인다',
   '{F41H 5/04,B32B 18/00}', 'REGISTERED', '2016-10-14', '2018-09-03', 'SELF', NULL),
  (102, '10-2020-0088777', '10-2411777', '항공기 2차 구조물용 열가소성 복합재 프레스 성형 방법',
   '예열·가압 조건을 단계별로 제어해 성형 주기를 줄인다', '{B29C 70/46,B64C 1/00}', 'REGISTERED',
   '2020-07-17', '2022-08-25', 'SELF', NULL),
  (103, '10-2024-0031999', NULL, '열상 영상에서 소형 표적을 검출하는 경량 신경망 추론 장치',
   '소형 표적용 특징 피라미드와 양자화로 임베디드 보드에서 실시간 추론', '{G06V 10/82,G06T 7/00}', 'APPLIED',
   '2024-03-08', NULL, 'SELF', NULL);

-- 인증·지정
INSERT INTO company_certification (organization_id, cert_type_code, cert_no, issuer, issued_on, expires_on,
                                   origin, verified_at) VALUES
  (101, 'VENTURE',         'V-2024-101', '벤처기업확인기관',     '2024-05-10', '2027-05-09', 'SELF', NULL),
  (101, 'RND_LAB',         'L-2013-101', '한국산업기술진흥협회', '2013-02-01', NULL,         'SELF', NULL),
  (101, 'ISO9001',         'Q-2023-101', '(가상)인증원',        '2023-11-01', '2026-10-31', 'SELF', NULL),  -- 만료
  (102, 'INNOBIZ',         'I-2024-102', '중소벤처기업부',       '2024-01-15', '2027-01-14', 'SELF', NULL),
  (102, 'AS9100',          'A-2025-102', '(가상)인증원',        '2025-03-01', '2028-02-28', 'SELF', NULL),
  (102, 'DEFENSE_COMPANY', 'D-2011-102', '산업통상자원부',       '2011-06-30', NULL,         'STAFF', now()),
  (102, 'DEFENSE_QMS',     'K-2024-102', '국방기술품질원',       '2024-09-01', '2027-08-31', 'SELF', NULL),
  (102, 'RND_LAB',         'L-2007-102', '한국산업기술진흥협회', '2007-04-01', NULL,         'SELF', NULL),
  (103, 'VENTURE',         'V-2025-103', '벤처기업확인기관',     '2025-02-01', '2028-01-31', 'SELF', NULL);

-- 신용등급 (NICE/KED 는 목업값)
INSERT INTO company_credit_rating (organization_id, agency, grade, rated_on, valid_until, origin, verified_at) VALUES
  (101, 'NICE', 'BBB-', '2026-04-10', '2027-04-09', 'EXTERNAL', now()),
  (102, 'KED',  'A-',   '2026-05-20', '2027-05-19', 'EXTERNAL', now()),
  (103, 'SELF', 'B+',   '2026-01-15', NULL,         'SELF',     NULL);

-- R&D 이력
INSERT INTO company_rnd_history (organization_id, project_no, title, funding_agency, start_date, end_date,
                                 amount_krw, role, summary, internal_project_id, origin, verified_at)
SELECT v.org, v.pno, v.title, v.agency, v.s::date, v.e::date, v.amt, v.role, v.summary,
       (SELECT id FROM project WHERE project_no = v.pno), v.origin, CASE WHEN v.origin = 'INTERNAL' THEN now() END
  FROM (VALUES
    (101, 'PRJ-2022-001', '소형 무인기용 항재밍 데이터링크 개발', '국방기술연구원', '2022-01-01', '2024-12-31',
     1200000000::bigint, 'PARTICIPANT', '주파수 도약 모뎀 시제 제작 참여', 'INTERNAL'),
    (101, 'NTIS-2020-118845', '전술 무전기용 저전력 RF 프런트엔드 국산화', '(가상)산업기술평가관리원', '2020-04-01', '2022-03-31',
     650000000::bigint, 'LEAD', '수입 RF 모듈 대체품 개발, TRL 6 달성', 'SELF'),
    (102, 'NTIS-2019-220011', '차세대 개인 방탄판 경량화 기술', '(가상)국방기술진흥연구소', '2019-05-01', '2022-04-30',
     2400000000::bigint, 'LEAD', '방호 등급 유지, 무게 18% 감소', 'SELF'),
    (102, 'NTIS-2023-330456', '무인기 동체용 열가소성 복합재 적용', '(가상)산업기술평가관리원', '2023-06-01', '2026-05-31',
     1800000000::bigint, 'PARTICIPANT', '성형 공정 개발 담당', 'SELF')
  ) AS v(org, pno, title, agency, s, e, amt, role, summary, origin);

-- 칸별 출처
INSERT INTO company_field_source (organization_id, field_name, value, source_kind, external_source_id, is_verified, verified_at)
SELECT v.org, v.field, v.val::jsonb, v.kind, (SELECT id FROM external_source WHERE code = v.src),
       v.ver, CASE WHEN v.ver THEN now() END
  FROM (VALUES
    (101, 'company_name',        '"(가상)한빛전자통신"', 'SELF',     NULL,      false),
    (101, 'employee_count',      '85',                  'SELF',     NULL,      false),
    (101, 'annual_revenue_krw',  '18200000000',         'SELF',     NULL,      false),
    (101, 'region',              '"대전"',               'SELF',     NULL,      false),
    (101, 'representative_name', '"김한빛"',             'EXTERNAL', 'NTS_BIZ', true),
    (101, 'opened_on',           '"2012-03-15"',        'EXTERNAL', 'NTS_BIZ', true),
    (101, 'business_status',     '"ACTIVE"',            'EXTERNAL', 'NTS_BIZ', true),
    (102, 'company_name',        '"(가상)누리복합소재"', 'SELF',     NULL,      false),
    (102, 'employee_count',      '320',                 'SELF',     NULL,      false),
    (102, 'annual_revenue_krw',  '124000000000',        'SELF',     NULL,      false),
    (102, 'annual_revenue_krw',  '119800000000',        'EXTERNAL', 'DART',    true),
    (102, 'region',              '"경남"',               'SELF',     NULL,      false),
    (102, 'representative_name', '"이누리"',             'EXTERNAL', 'NTS_BIZ', true),
    (102, 'opened_on',           '"2005-09-02"',        'EXTERNAL', 'NTS_BIZ', true),
    (102, 'business_status',     '"ACTIVE"',            'EXTERNAL', 'NTS_BIZ', true),
    (103, 'company_name',        '"(가상)새봄비전AI"',   'SELF',     NULL,      false),
    (103, 'employee_count',      '14',                  'SELF',     NULL,      false),
    (103, 'annual_revenue_krw',  '900000000',           'SELF',     NULL,      false),
    (103, 'region',              '"경기"',               'SELF',     NULL,      false),
    (103, 'representative_name', '"박새봄"',             'SELF',     NULL,      false),
    (103, 'opened_on',           '"2021-06-01"',        'SELF',     NULL,      false)
  ) AS v(org, field, val, kind, src, ver);

-- 시퀀스
DO $$ BEGIN
  PERFORM setval(pg_get_serial_sequence('ax.organization', 'id'), GREATEST((SELECT max(id) FROM ax.organization), 10));
END $$;

COMMIT;

-- 확인용 요약
SELECT o.id, o.business_reg_no, o.name, cp.region, cp.company_size, cp.biz_verify_status,
       (SELECT count(*) FROM ax.company_patent p WHERE p.organization_id = o.id)        AS patents,
       (SELECT count(*) FROM ax.company_certification c WHERE c.organization_id = o.id) AS certs,
       (SELECT count(*) FROM ax.company_rnd_history h WHERE h.organization_id = o.id)   AS rnd
  FROM ax.organization o JOIN ax.company_profile cp ON cp.organization_id = o.id
 WHERE o.id IN (101,102,103) ORDER BY o.id;
