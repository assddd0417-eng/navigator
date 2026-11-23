-- 성장경로 연계 기준 (가상). navigator_consult.sql 다음에 실행
--   사업 추가: 국방벤처 혁신기술, 방산 중소수출길, 방산전시회 참가 (근거 공고 각 1건)
--   program_route: 방산진입 > 기술개발 > 양산·수출 단계별 사업, 다음 연계사업, 진입조건, 준비과제
--   지원 이력: 유사 기업 사례 근거용 (102 누리, 103 새봄)
-- 재실행 가능: psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f seeds/navigator_route.sql
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL search_path = ax, public;

INSERT INTO program (program_code, name, program_type_code, purpose) VALUES
  ('P-INNOV',  '국방벤처 혁신기술 지원(가상)', 'DEFENSE_VENTURE', '국방벤처센터 협약기업의 군 수요 기반 기술개발 지원'),
  ('P-EXPORT', '방산 중소수출길 지원(가상)',   'EXPORT_SUPPORT',  '방산 중소기업의 해외 인증·마케팅·바이어 발굴 지원'),
  ('P-EXPO',   '방산전시회 참가 지원(가상)',   'EXPORT_SUPPORT',  '해외 방산전시회 공동관 참가와 상담 지원')
ON CONFLICT (program_code) DO NOTHING;

-- 근거 공고 (공고번호 기준, id 는 순번대로)
INSERT INTO announcement (announcement_no, title, agency_name, domain, program_id, summary, target_desc,
                          support_amount_krw, support_period_months, receipt_start, receipt_end, source_kind, status,
                          company_burden, submit_documents, requirements_confirmed_at)
SELECT v.no, v.title, v.agency, 'GENERAL_SUPPORT', (SELECT id FROM program WHERE program_code = v.prog),
       v.summary, v.target, v.amount, v.months, v.rs::date, v.re::date, 'MANUAL', 'PUBLISHED',
       v.burden, v.docs::jsonb, now()
  FROM (VALUES
    ('NAV-2027-108', '2027년 국방벤처 혁신기술 지원사업 공고(가상)', '(가상)국방기술진흥원', 'P-INNOV',
     '국방벤처센터 협약기업이 보유한 기술을 군 수요에 맞게 개발·시험할 수 있도록 개발비를 지원한다',
     '국방벤처센터 협약 중소기업, 적용 무기체계 후보 보유', 300000000::bigint, 12::smallint,
     '2027-02-02', '2027-03-06', '총사업비 25% (현금 10%)',
     '[{"name":"사업계획서","required":true},{"name":"국방벤처센터 협약서","required":true},{"name":"수요 확인서","required":false}]'),
    ('NAV-2026-109', '''26년 방산 중소수출길 지원사업 참여기업 모집(가상)', '(가상)방위산업진흥회', 'P-EXPORT',
     '방산 중소기업의 해외 품질인증 취득, 수출 마케팅, 해외 바이어 발굴을 지원한다',
     '방산 실적 또는 군 납품 실적이 있는 중소기업', 100000000::bigint, 10::smallint,
     '2026-11-20', '2026-12-26', '지원금의 30%',
     '[{"name":"참가신청서","required":true},{"name":"수출 실적 증명","required":false},{"name":"군 납품 실적 증명","required":true}]'),
    ('NAV-2025-110', '2025년 해외 방산전시회 공동관 참가기업 모집(가상)', '(가상)방위산업진흥회', 'P-EXPO',
     '해외 방산전시회 한국 공동관 부스와 통역, 현지 상담회를 지원한다',
     '수출 가능 품목을 보유한 방산 중소기업', 30000000::bigint, 6::smallint,
     '2025-03-03', '2025-03-28', '부스 임차료 20%',
     '[{"name":"참가신청서","required":true},{"name":"영문 제품 소개서","required":true}]')
  ) AS v(no, title, agency, prog, summary, target, amount, months, rs, re, burden, docs)
ON CONFLICT (announcement_no) DO UPDATE SET
  title = EXCLUDED.title, agency_name = EXCLUDED.agency_name, program_id = EXCLUDED.program_id,
  summary = EXCLUDED.summary, target_desc = EXCLUDED.target_desc, support_amount_krw = EXCLUDED.support_amount_krw,
  support_period_months = EXCLUDED.support_period_months, receipt_start = EXCLUDED.receipt_start,
  receipt_end = EXCLUDED.receipt_end, status = 'PUBLISHED', company_burden = EXCLUDED.company_burden,
  submit_documents = EXCLUDED.submit_documents;

DELETE FROM announcement_requirement
 WHERE announcement_id IN (SELECT id FROM announcement WHERE announcement_no IN ('NAV-2027-108', 'NAV-2026-109', 'NAV-2025-110'));
INSERT INTO announcement_requirement (announcement_id, req_type_code, rule, is_mandatory, description, source_quote,
                                      origin, sort_order)
SELECT a.id, v.type, v.rule::jsonb, v.mand, v.descr, v.quote, 'MANUAL', v.ord
  FROM (VALUES
    ('NAV-2027-108', 'COMPANY_SIZE', '{"allowed":["SME","STARTUP","VENTURE"]}', true, '중소기업',
     '신청자격: 국방벤처센터 협약 중소기업', 0),
    ('NAV-2027-108', 'BUSINESS_STATUS', '{"allowed":["ACTIVE"]}', true, '휴·폐업 아님', NULL, 1),
    ('NAV-2027-108', 'NO_DISQUALIFICATION', '{"checks":["TAX_DELINQUENT","RND_RESTRICTED"]}', true,
     '체납·국가 R&D 참여제한 없음', '국세·지방세 체납 또는 국가연구개발사업 참여제한 중인 기업 제외', 2),
    ('NAV-2026-109', 'COMPANY_SIZE', '{"allowed":["SME","STARTUP","VENTURE"]}', true, '중소기업',
     '지원대상: 방산 실적 또는 군 납품 실적이 있는 중소기업', 0),
    ('NAV-2026-109', 'DEFENSE_COMPANY', '{"required":true}', false, '방산업체 지정 우대', '방산업체 지정 기업 우대', 1),
    ('NAV-2026-109', 'NO_DISQUALIFICATION', '{"checks":["TAX_DELINQUENT","PROCUREMENT_SANCTIONED"]}', true,
     '체납·부정당제재 없음', '국세 체납 또는 부정당업자 제재 중인 기업 제외', 2),
    ('NAV-2025-110', 'COMPANY_SIZE', '{"allowed":["SME","STARTUP","VENTURE"]}', true, '중소기업',
     '참가대상: 수출 가능 품목을 보유한 방산 중소기업', 0)
  ) AS v(no, type, rule, mand, descr, quote, ord)
  JOIN announcement a ON a.announcement_no = v.no;

-- 성장경로 연계 기준
DELETE FROM program_route;
INSERT INTO program_route (program_id, stage_code, next_program_ids, entry_condition, entry_min_scores, prep_tasks,
                           expected_output, repeatable, sort_order)
SELECT p.id, v.stage,
       ARRAY(SELECT n.id FROM program n WHERE n.program_code = ANY(v.next) ORDER BY n.id),
       v.cond, v.mins::jsonb, v.tasks, v.output, v.rep, v.ord
  FROM (VALUES
    ('P-VENTURE', 'ENTRY', '{P-INNOV,P-LOC}'::text[], '국방 분야 적용 가능 기술 보유', '{}',
     '{"적용 무기체계 후보 특정","국방벤처센터 협약 신청서 준비"}'::text[], '국방벤처센터 협약, 군 수요 설명회 참여', false, 1),
    ('P-CONSULT', 'ENTRY', '{P-INNOV,P-LOC}', '방산 진출 희망 중소기업', '{}',
     '{"DQMS 품질보증체계 준비","컨설팅 수행계획 작성"}', '품질체계 진단, 수요처 발굴 계획', false, 2),
    ('P-INNOV', 'TECH_DEV', '{P-RAPID,P-EXPORT}', '국방벤처센터 협약, 기술 60점·방산진입 30점 이상',
     '{"TECH":60,"DEFENSE":30}', '{"체계기업 수요 확인·과제 기획","시험평가 계획 수립"}', '군 수요 기반 시제품, 시험성적서', false, 1),
    ('P-LOC', 'TECH_DEV', '{P-EXPORT}', '국산화 대상 부품 식별, 기술 60점·방산진입 40점 이상',
     '{"TECH":60,"DEFENSE":40}', '{"국산화 대상 부품 식별","체계기업 수요 확인서 확보"}', '국산화 부품 개발, 군 적용 시험', false, 2),
    ('P-RAPID', 'TECH_DEV', '{P-EXPORT}', 'TRL 6 이상 민간 신기술, 기술 70점 이상',
     '{"TECH":70}', '{"시범 적용 부대·장비 협의","운용 시험 계획 수립"}', '군 시범 운용 결과', false, 3),
    ('P-CORE', 'TECH_DEV', '{P-EXPORT}', '국방 R&D 과제 수행 역량, 기술 70점·품질·인증 50점 이상',
     '{"TECH":70,"QUALITY":50}', '{"과제 제안서 준비","연구 인력 확보"}', '핵심기술 개발 성과', true, 4),
    ('P-EXPORT', 'SCALE', '{P-EXPO}', '군 납품 또는 방산 실적, 생산·공급망 50점·수출 40점 이상',
     '{"PRODUCTION":50,"EXPORT":40}', '{"수출 가능 품목 확정","해외 품질인증 취득"}', '해외 인증, 바이어 상담 실적', false, 1),
    ('P-EXPO', 'SCALE', '{}', '수출 가능 품목 보유, 수출 30점 이상',
     '{"EXPORT":30}', '{"영문 제품 소개서 준비","목표 국가 선정"}', '해외 전시 참가, 수출 상담', true, 2)
  ) AS v(code, stage, next, cond, mins, tasks, output, rep, ord)
  JOIN program p ON p.program_code = v.code;

-- 유사 기업 사례 (지원 이력)
DELETE FROM company_support_history WHERE organization_id IN (102, 103) AND origin = 'STAFF'
   AND program_name LIKE '%(가상 사례)';
INSERT INTO company_support_history (organization_id, program_name, agency, year, result, summary, origin) VALUES
  (102, '국방벤처 육성 (가상 사례)',           '(가상)창원국방벤처센터', 2019, 'COMPLETED', '협약기업 지원', 'STAFF'),
  (102, '국방벤처 혁신기술 지원 (가상 사례)', '(가상)국방기술진흥원',   2021, 'COMPLETED', '복합재 시제품 개발', 'STAFF'),
  (102, '방산 중소수출길 지원 (가상 사례)',   '(가상)방위산업진흥회',   2025, 'COMPLETED', '해외 품질인증 취득', 'STAFF'),
  (103, '국방벤처 육성 (가상 사례)', '(가상)경기국방벤처센터', 2025, 'COMPLETED', '협약기업 지원', 'STAFF');

COMMIT;
