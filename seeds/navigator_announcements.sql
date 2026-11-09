-- Navigator 테스트 공고 5건 (가상). 기대 판정은 docs/navigator.md 참고.
--   101 부품국산화(접수중) 102 방탄 복합소재(접수중) 103 AI 영상 신속시범(접수중)
--   104 강원 국방벤처(접수전) 105 하반기 공모(마감)
-- 재실행 가능: psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f seeds/navigator_announcements.sql
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL search_path = ax, public;

-- 사업트랙
INSERT INTO program (program_code, name, program_type_code, purpose) VALUES
  ('P-VENTURE', '국방벤처 육성(가상)',   'DEFENSE_VENTURE', '창업·벤처 기업의 국방 진입 지원'),
  ('P-RAPID',   '신속시범사업(가상)',    'RAPID_PILOT',     '민간 신기술을 군에 빠르게 시범 적용')
ON CONFLICT (program_code) DO NOTHING;

INSERT INTO announcement (id, announcement_no, title, agency_name, domain, program_id, summary, target_desc,
                          support_amount_krw, support_period_months, receipt_start, receipt_end, source_kind,
                          status) OVERRIDING SYSTEM VALUE
SELECT v.id, v.no, v.title, v.agency, 'DEFENSE_RND', (SELECT id FROM program WHERE program_code = v.prog),
       v.summary, v.target, v.amount, v.months, v.rs::date, v.re::date, 'MANUAL', 'PUBLISHED'
  FROM (VALUES
    (101, 'NAV-2026-101', '2027년 전술통신 부품국산화 개발지원 사업 공고(가상)', '(가상)국방기술진흥원', 'P-LOC',
     '수입에 의존하는 전술통신 부품(데이터링크 모뎀, RF 모듈)의 국산화 개발을 지원한다',
     '기업부설연구소 또는 연구개발전담부서를 보유한 중소기업', 1500000000::bigint, 24::smallint,
     '2026-11-01', '2026-12-15'),
    (102, 'NAV-2026-102', '경량 방탄 복합소재 핵심기술 개발 과제 공모(가상)', '(가상)국방기술진흥원', 'P-CORE',
     '개인·차량 방호용 경량 복합소재의 방호 성능 향상과 경량화 기술을 확보한다',
     '업력 7년 이상, 항공·국방 품질인증을 보유한 중소·중견기업', 3000000000::bigint, 36::smallint,
     '2026-11-05', '2026-12-31'),
    (103, 'NAV-2026-103', 'AI 기반 EO/IR 영상 표적탐지 신속시범사업 공고(가상)', '(가상)국방신속획득기술원', 'P-RAPID',
     '민간 AI 영상 기술을 감시정찰 장비에 시범 적용해 소형 표적 탐지 성능을 검증한다',
     '업력 7년 이하 창업·중소기업, 제안 기술 TRL 6 이상', 800000000::bigint, 12::smallint,
     '2026-11-09', '2026-11-30'),
    (104, 'NAV-2026-104', '강원 접경지역 국방벤처 육성 지원 공고(가상)', '(가상)강원국방벤처센터', 'P-VENTURE',
     '강원 접경지역에 본사를 둔 창업 기업의 국방 시장 진입을 돕는다',
     '강원 소재, 직원 10명 이하 스타트업·벤처기업', 200000000::bigint, 12::smallint,
     '2026-11-16', '2026-12-18'),
    (105, 'NAV-2026-105', '2026년 하반기 국방 R&D 과제 공모(가상)', '(가상)국방기술진흥원', 'P-CORE',
     '무인체계 전술통신·생존성 분야 국방 R&D 과제를 공모한다',
     'R&D 과제 주관 수행 경험이 있고 보안측정을 통과한 기업', 2000000000::bigint, 30::smallint,
     '2026-10-01', '2026-10-31')
  ) AS v(id, no, title, agency, prog, summary, target, amount, months, rs, re)
ON CONFLICT (id) DO UPDATE SET
  announcement_no = EXCLUDED.announcement_no, title = EXCLUDED.title, agency_name = EXCLUDED.agency_name,
  domain = EXCLUDED.domain, program_id = EXCLUDED.program_id, summary = EXCLUDED.summary,
  target_desc = EXCLUDED.target_desc, support_amount_krw = EXCLUDED.support_amount_krw,
  support_period_months = EXCLUDED.support_period_months, receipt_start = EXCLUDED.receipt_start,
  receipt_end = EXCLUDED.receipt_end, source_kind = EXCLUDED.source_kind, status = EXCLUDED.status;

DELETE FROM announcement_requirement WHERE announcement_id BETWEEN 101 AND 105;
DELETE FROM announcement_tech_need   WHERE announcement_id BETWEEN 101 AND 105;
DELETE FROM announcement_embedding   WHERE announcement_id BETWEEN 101 AND 105;  -- 요구기술 id 가 바뀌므로 다시 임베딩

-- 자격요건
INSERT INTO announcement_requirement (announcement_id, req_type_code, rule, is_mandatory, description,
                                      source_quote, source_page, sort_order)
SELECT v.ann, v.type, v.rule::jsonb, v.mand, v.descr, v.quote, v.page, v.ord
  FROM (VALUES
    -- 101 전술통신 부품국산화
    (101, 'COMPANY_SIZE',     '{"allowed":["SME","STARTUP","VENTURE"]}', true,  '중소기업(창업·벤처 포함)', '신청자격: 「중소기업기본법」에 따른 중소기업', 2, 0),
    (101, 'REQUIRED_CERT',    '{"any_of":["RND_LAB","RND_DEPT"]}',       true,  '기업부설연구소 또는 연구개발전담부서 보유', '기업부설연구소 또는 연구개발전담부서를 보유한 기업', 2, 1),
    (101, 'MIN_CREDIT_GRADE', '{"min_grade":"B"}',                       true,  '기업신용등급 B 이상', '신용평가등급 B 이상 (평가서 제출)', 3, 2),
    (101, 'BUSINESS_STATUS',  '{"allowed":["ACTIVE"]}',                  true,  '휴·폐업 상태가 아닐 것', '휴업 또는 폐업 중인 기업은 신청 불가', 3, 3),
    (101, 'RND_EXPERIENCE',   '{"min_count":1}',                         false, '국가 R&D 수행 경험 우대', '최근 5년 내 국가 R&D 수행 실적 보유 시 가점', 4, 4),
    (101, 'PATENT',           '{"min_count":1,"ipc_prefixes":["H04"]}',  false, '통신 분야(IPC H04) 특허 보유 우대', '관련 분야 지식재산권 보유 시 가점', 4, 5),
    -- 102 경량 방탄 복합소재
    (102, 'COMPANY_SIZE',     '{"allowed":["SME","MIDSIZE"]}',           true,  '중소·중견기업', '신청자격: 중소기업 또는 중견기업', 2, 0),
    (102, 'BUSINESS_AGE',     '{"min_years":7}',                         true,  '업력 7년 이상 (접수 마감일 기준)', '개업일로부터 7년 이상 경과한 기업', 2, 1),
    (102, 'REQUIRED_CERT',    '{"any_of":["AS9100","DEFENSE_QMS"]}',     true,  'AS9100 또는 국방품질경영체제 인증 보유', '항공우주 품질경영(AS9100) 또는 국방품질경영체제 인증 보유', 2, 2),
    (102, 'MIN_CREDIT_GRADE', '{"min_grade":"BBB-"}',                    true,  '기업신용등급 BBB- 이상', '신용평가등급 BBB- 이상', 3, 3),
    (102, 'DEFENSE_COMPANY',  '{"required":true}',                       false, '방산업체 지정 기업 우대', '방산업체로 지정된 기업은 가점', 4, 4),
    -- 103 AI 영상 신속시범
    (103, 'BUSINESS_AGE',     '{"max_years":7}',                         true,  '업력 7년 이하', '창업 7년 이내 기업', 1, 0),
    (103, 'COMPANY_SIZE',     '{"allowed":["SME","STARTUP","VENTURE"]}', true,  '중소·창업·벤처기업', '중소기업(창업·벤처 포함)', 1, 1),
    (103, 'TRL',              '{"min":6}',                               true,  '제안 기술의 TRL 6 이상', '제안 기술은 기술성숙도(TRL) 6 이상이어야 함', 2, 2),
    (103, 'MIN_CREDIT_GRADE', '{"min_grade":"B"}',                       true,  '기업신용등급 B 이상', '신용평가등급 B 이상', 2, 3),
    (103, 'PATENT',           '{"min_count":1,"ipc_prefixes":["G06"]}',  false, '영상 AI 분야(IPC G06) 특허 우대', '관련 특허(출원 포함) 보유 시 가점', 3, 4),
    -- 104 강원 접경지역
    (104, 'REGION',           '{"allowed":["강원"]}',                     true,  '본사 소재지 강원', '공고일 현재 강원특별자치도에 본사를 둔 기업', 1, 0),
    (104, 'COMPANY_SIZE',     '{"allowed":["STARTUP","VENTURE"]}',       true,  '스타트업·벤처기업', '창업기업 또는 벤처기업', 1, 1),
    (104, 'EMPLOYEE_COUNT',   '{"max":10}',                              true,  '상시 근로자 10명 이하', '상시 근로자 10인 이하', 1, 2),
    -- 105 하반기 과제 공모
    (105, 'BUSINESS_STATUS',  '{"allowed":["ACTIVE"]}',                  true,  '휴·폐업 상태가 아닐 것', '휴업 또는 폐업 중인 기업은 신청 불가', 2, 0),
    (105, 'RND_EXPERIENCE',   '{"min_count":1,"role":"LEAD"}',           true,  'R&D 과제 주관 수행 경험 1건 이상', '국가 R&D 과제를 주관기관으로 수행한 실적', 2, 1),
    (105, 'OTHER',            '{}',                                      true,  '보안측정(방위사업청) 통과 기업', '방위사업청 보안측정을 통과한 기업에 한함', 3, 2)
  ) AS v(ann, type, rule, mand, descr, quote, page, ord);

-- 요구 기술
INSERT INTO announcement_tech_need (announcement_id, tech_name, description, ipc_codes, is_core, sort_order)
SELECT v.ann, v.name, v.descr, v.ipc::text[], v.core, v.ord
  FROM (VALUES
    (101, '항재밍 주파수 도약 데이터링크 모뎀', '광대역 재밍 환경에서 동기를 유지하는 소형 무인기용 모뎀', '{H04B 1/713,H04K 3/00}', true, 0),
    (101, '전술 무전기 RF 프런트엔드 모듈', '수입 RF 모듈을 대체하는 저전력 송수신 모듈', '{H04B 1/40}', false, 1),
    (102, '세라믹-탄소섬유 경량 복합 방탄판', '같은 방호 등급에서 무게를 줄인 개인·차량 방호재', '{F41H 5/04,B32B 18/00}', true, 0),
    (102, '열가소성 복합재 대량 성형 공정', '방호재·구조물 양산을 위한 성형 주기 단축', '{B29C 70/46}', false, 1),
    (103, 'EO/IR 영상 소형 표적 자동탐지 AI', '열상·주간 영상에서 소형 드론·인원을 실시간 탐지', '{G06V 10/82,G06T 7/00}', true, 0),
    (103, '임베디드 경량 추론 모듈', '감시장비 탑재용 저전력 추론 보드', '{G06N 3/063}', false, 1),
    (104, '접경지역 경계 감시 센서', '저비용 무인 경계 감시 센서', '{G08B 13/00}', true, 0),
    (105, '무인체계 전술통신 생존성 향상', '재밍·단절 환경에서 무인체계 통신 유지', '{H04W 84/18,H04B 1/713}', true, 0)
  ) AS v(ann, name, descr, ipc, core, ord);

DO $$ BEGIN
  PERFORM setval(pg_get_serial_sequence('ax.announcement', 'id'), GREATEST((SELECT max(id) FROM ax.announcement), 10));
END $$;

COMMIT;

-- 확인용 요약
SELECT id, announcement_no, title, receipt_state, mandatory_count, requirement_count, tech_need_count
  FROM ax.v_announcement WHERE id BETWEEN 101 AND 105 ORDER BY id;
