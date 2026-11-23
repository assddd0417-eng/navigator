-- 기업 상담용 가상 데이터 (navigator_companies.sql 다음에 실행)
--   D-STATE 보완 답변: 101 한빛(방산진입 준비), 102 누리(수출 확장), 103 새봄(기초역량 정비)
--   공고 NAV-2026-107 방산 중소기업 컨설팅(가상, id 는 순번 그대로): 평가항목·배점, 기업부담, 제출서류, 신청제한(중복수혜·부정당제재)
--   공고 101 평가항목
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

UPDATE company_profile SET procurement_sanctioned = false WHERE organization_id IN (101, 102);

DELETE FROM company_support_history WHERE organization_id IN (101, 102) AND origin = 'SELF';
INSERT INTO company_support_history (organization_id, program_name, agency, year, result, summary, origin) VALUES
  (101, '국방벤처센터 협약기업 지원', '(가상)대전국방벤처센터', 2024, 'COMPLETED', '시험평가 장비 사용, 군 수요 설명회', 'SELF'),
  (102, '방산 중소기업 컨설팅 지원', '(가상)방위산업진흥회', 2023, 'COMPLETED', '수출 품질인증 컨설팅', 'SELF'),
  (102, '무기체계 부품국산화개발 지원', '(가상)국방기술진흥원', 2024, 'SELECTED', '복합재 구조물 국산화', 'SELF');

INSERT INTO program (program_code, name, program_type_code, purpose) VALUES
  ('P-CONSULT', '방산 중소기업 컨설팅 지원(가상)', 'DEFENSE_VENTURE', '민간 중소기업의 방산 분야 참여 확대와 경쟁력 강화')
ON CONFLICT (program_code) DO NOTHING;

INSERT INTO announcement (announcement_no, title, agency_name, domain, program_id, summary, target_desc,
                          support_amount_krw, support_period_months, receipt_start, receipt_end, source_kind, status,
                          company_burden, submit_documents, requirements_confirmed_at)
VALUES ('NAV-2026-107', '''26-1차 방산 중소기업 컨설팅 지원사업(가상)', '(가상)방위산업진흥회', 'GENERAL_SUPPORT',
        (SELECT id FROM program WHERE program_code = 'P-CONSULT'),
        '기술력을 갖춘 민간 중소기업의 방산 분야 참여를 확대하고 방산 중소기업의 경쟁력을 강화하기 위해 방산 전문가의 맞춤형 컨설팅(기술·경영·법률·행정)을 지원한다. 품질체계 구축, 수요처 발굴, 인증 준비 등',
        '방산 중소기업 또는 방산분야 진출을 희망하는 중소기업', 30000000, 12,
        '2026-11-16', '2026-12-31', 'MANUAL', 'PUBLISHED', '컨설팅 비용 25%',
        '[{"name":"사업자등록증","required":true},{"name":"중소기업 확인서","required":true},
          {"name":"최근 2년 재무제표","required":true},{"name":"정부지원금 부정수급 여부 확인서","required":true},
          {"name":"청렴서약서","required":true},{"name":"국방벤처센터 협약서 (우대 해당 시)","required":false}]',
        now())
ON CONFLICT (announcement_no) DO UPDATE SET title = EXCLUDED.title, agency_name = EXCLUDED.agency_name, summary = EXCLUDED.summary, program_id = EXCLUDED.program_id,
  receipt_start = EXCLUDED.receipt_start, receipt_end = EXCLUDED.receipt_end, status = 'PUBLISHED',
  company_burden = EXCLUDED.company_burden, submit_documents = EXCLUDED.submit_documents
RETURNING id AS consult_ann \gset

DELETE FROM announcement_requirement WHERE announcement_id = :consult_ann;
INSERT INTO announcement_requirement (announcement_id, req_type_code, rule, is_mandatory, description, source_quote,
                                      origin, sort_order, bonus_points) VALUES
  (:consult_ann, 'COMPANY_SIZE', '{"allowed":["SME","STARTUP","VENTURE"]}', true, '중소기업, 방산분야 진출 희망',
   '방산 중소기업 또는 방산분야 진출을 희망하는 중소기업 중 기술력을 갖춘 중소기업', 'MANUAL', 0, NULL),
  (:consult_ann, 'DUPLICATE_SUPPORT', '{"within_years":1}', true, '전년도 동일분야 수혜 없음',
   '전년도(''25년)에 지원 받은 컨설팅 분야와 동일 지원분야를 신청하는 경우', 'MANUAL', 1, NULL),
  (:consult_ann, 'OTHER', '{}', true, '유사 정부·지자체 컨설팅 지원 수혜 없음',
   '컨설팅 지원 신청내용과 유사한 내용으로 과거 또는 공고일 현재 정부기관, 지방자치단체 또는 관련기관으로부터 컨설팅 지원(금)을 받았거나 받고 있는 경우',
   'MANUAL', 2, NULL),
  (:consult_ann, 'BUSINESS_STATUS', '{"allowed":["ACTIVE"]}', true, '휴·폐업 아님', NULL, 'MANUAL', 3, NULL),
  (:consult_ann, 'NO_DISQUALIFICATION', '{"checks":["TAX_DELINQUENT","PROCUREMENT_SANCTIONED"]}', true, '체납·부정당제재 해당 없음',
   '부정당업자 제재 처분', 'MANUAL', 4, NULL),
  (:consult_ann, 'OTHER', '{}', false, '국방벤처센터 협약 중소기업', '국방벤처센터 협약 중소기업 1.5%', 'MANUAL', 5, 1.5),
  (:consult_ann, 'OTHER', '{}', false, '방산혁신기업 100 선정기업', '''방산혁신기업 100'' 선정기업 2%', 'MANUAL', 6, 2);

DELETE FROM announcement_eval_item WHERE announcement_id IN (101, :consult_ann);
INSERT INTO announcement_eval_item (announcement_id, name, points, kind, areas, source_quote, sort_order) VALUES
  (:consult_ann, '재무상황', 10, 'CAPABILITY', '{BUSINESS}', '재무상황(10점): 부채비율, 매출액증가율, 매출액영업이익률', 0),
  (:consult_ann, '기술성', 15, 'CAPABILITY', '{TECH,DEFENSE}', '기술성(15점): 기술 보유 및 납품 실적, 보유기술의 국방분야 연계 가능성', 1),
  (:consult_ann, '컨설팅 목적성', 15, 'PURPOSE', '{}', '기업이 요구하는 컨설팅 내용과 본 지원사업 목적과의 부합성', 2),
  (:consult_ann, '수행방안의 적정성', 40, 'APPLICATION', '{}', '컨설팅 목표 달성을 위한 수행방안의 구체성 및 적정성, 컨설턴트 적합성', 3),
  (:consult_ann, '기대효과', 20, 'APPLICATION', '{}', '컨설팅 지원의 기대효과의 구체성, 국방산업 진출 가능성', 4),
  (101, '기술개발 역량', 30, 'CAPABILITY', '{TECH}', NULL, 0),
  (101, '양산·공급 능력', 20, 'CAPABILITY', '{PRODUCTION,QUALITY}', NULL, 1),
  (101, '사업 목적 부합', 20, 'PURPOSE', '{}', NULL, 2),
  (101, '개발계획 적정성', 30, 'APPLICATION', '{}', NULL, 3);

COMMIT;
