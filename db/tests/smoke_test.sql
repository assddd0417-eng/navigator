-- 스모크 테스트: 샘플 데이터로 기업·공고·판정 흐름을 확인하고 ROLLBACK (DB 에 흔적 남기지 않음)
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/tests/smoke_test.sql
\set QUIET on
BEGIN;
SET search_path = ax, public;
SET LOCAL hnsw.ef_search = 100;

\echo '--- 사업자번호로 기업 넣고 조회'
INSERT INTO organization (id, name, org_type, business_reg_no) VALUES (900, '(가상)스모크기업', 'COMPANY', '9998400049');
INSERT INTO company_profile (organization_id, company_size, representative_name, opened_on, employee_count, region,
                             biz_verify_status, registered_email, registration_channel)
VALUES (900, 'SME', '홍길동', '2019-03-01', 10, '대전', 'UNVERIFIED', 'a@example.com', 'SELF');
INSERT INTO company_patent (organization_id, application_no, title, status) VALUES (900, '10-2026-0000001', '스모크 특허', 'APPLIED');
INSERT INTO company_certification (organization_id, cert_type_code) VALUES (900, 'VENTURE');
INSERT INTO company_credit_rating (organization_id, agency, grade) VALUES (900, 'SELF', 'BB');
INSERT INTO company_access_link (organization_id, email, token_hash, expires_at)
VALUES (900, 'a@example.com', repeat('a', 64), now() + interval '30 days');
INSERT INTO company_field_source (organization_id, field_name, value, source_kind) VALUES (900, 'employee_count', '10', 'SELF');
INSERT INTO company_field_source (organization_id, field_name, value, source_kind, external_source_id, is_verified, verified_at)
SELECT 900, 'employee_count', '12', 'EXTERNAL', id, true, now() FROM external_source WHERE code = 'DART';
SELECT o.name, cp.biz_verify_status, cp.region, (SELECT count(*) FROM company_patent WHERE organization_id = o.id) AS patents
  FROM organization o JOIN company_profile cp ON cp.organization_id = o.id WHERE o.business_reg_no = '9998400049';
SELECT field_name, preferred_value, differs FROM v_company_field_compare WHERE organization_id = 900;

\echo '--- 공고·자격요건'
INSERT INTO announcement (id, announcement_no, title, agency_name, receipt_start, receipt_end)
VALUES (900, 'SMOKE-001', '스모크 공고', '(가상)기관', current_date - 1, current_date + 30),
       (901, 'SMOKE-002', '마감 공고', '(가상)기관', current_date - 60, current_date - 1);
INSERT INTO announcement_requirement (announcement_id, req_type_code, rule, is_mandatory, description) VALUES
  (900, 'MIN_CREDIT_GRADE', '{"min_grade":"BB-"}', true, 'BB- 이상'),
  (900, 'PATENT', '{"min_count":1}', false, '특허 우대');
INSERT INTO announcement_tech_need (announcement_id, tech_name) VALUES (900, '항재밍 모뎀');
SELECT announcement_no, receipt_state, mandatory_count, requirement_count, tech_need_count
  FROM v_announcement WHERE id IN (900, 901) ORDER BY id;
-- 최저신용등급 비교: 기업 등급 서열 ≥ 요건 등급 서열
SELECT cr.grade AS company_grade, r.rule->>'min_grade' AS min_grade, cg.rank >= rg.rank AS meets
  FROM company_credit_rating cr JOIN code_credit_grade cg ON cg.grade = cr.grade
  CROSS JOIN announcement_requirement r JOIN code_credit_grade rg ON rg.grade = r.rule->>'min_grade'
 WHERE cr.organization_id = 900 AND r.announcement_id = 900;

\echo '--- 매칭 실행·판정·근거·보완질문 답'
INSERT INTO company_embedding (organization_id, facet, model_id, source_text, source_sha256, embedding)
SELECT 900, 'SUMMARY', id, '스모크기업', repeat('0', 64), array_fill(0.01, ARRAY[1024])::vector FROM embedding_model WHERE is_active;
INSERT INTO announcement_embedding (announcement_id, facet, model_id, source_text, source_sha256, embedding)
SELECT 900, 'SUMMARY', id, '스모크 공고', repeat('0', 64), array_fill(0.01, ARRAY[1024])::vector FROM embedding_model WHERE is_active;
INSERT INTO company_match_run (id, direction, announcement_id, model_id, rule_snapshot, requested_via)
SELECT 900, 'ANNOUNCEMENT_TO_COMPANY', 900, id, '{"version":"smoke"}', 'SYSTEM' FROM embedding_model WHERE is_active;
INSERT INTO company_recommendation (id, match_run_id, organization_id, announcement_id, rank, total_score, verdict,
                                    mandatory_met, mandatory_total, rationale)
VALUES (900, 900, 900, 900, 1, 0.5, 'ELIGIBLE', 1, 1, '[적합] 스모크');
INSERT INTO company_recommendation_score (recommendation_id, criterion, score, weight, method)
VALUES (900, 'TECH', 0.4, 0.45, 'cosine'), (900, 'PREFERENCE', 1, 0.2, 'rule');
INSERT INTO eligibility_check (recommendation_id, requirement_id, result, is_mandatory, reason)
SELECT 900, id, 'MET', is_mandatory, '충족' FROM announcement_requirement WHERE announcement_id = 900;
INSERT INTO eligibility_answer (organization_id, requirement_id, answer, answered_via)
SELECT 900, id, '{"value": true}', 'COMPANY_LINK' FROM announcement_requirement WHERE announcement_id = 900 AND NOT is_mandatory;
SELECT cr.verdict, cr.total_score, (SELECT count(*) FROM eligibility_check WHERE recommendation_id = cr.id) AS checks,
       (SELECT 1 - (c.embedding <=> a.embedding) FROM company_embedding c, announcement_embedding a
         WHERE c.organization_id = 900 AND a.announcement_id = 900) AS summary_sim
  FROM company_recommendation cr WHERE cr.id = 900;
-- 보완질문은 모름(UNKNOWN)일 때만
DO $$ BEGIN
  INSERT INTO ax.announcement_requirement (id, announcement_id, req_type_code, rule, description)
  VALUES (900901, 901, 'TRL', '{"min":6}', 'TRL 6 이상');
  INSERT INTO ax.eligibility_check (recommendation_id, requirement_id, result, is_mandatory, reason, question)
  VALUES (900, 900901, 'MET', true, 'x', '질문');
  RAISE EXCEPTION 'MET 판정에 보완질문이 들어감';
EXCEPTION WHEN check_violation THEN RAISE NOTICE 'OK: 충족 판정에는 보완질문을 넣을 수 없음';
END $$;

ROLLBACK;
\echo '스모크 테스트 완료 (ROLLBACK)'
