-- =============================================================================
-- 스모크 테스트: 샘플 데이터로 전체 흐름 검증 후 ROLLBACK (DB 에 흔적 남기지 않음)
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/tests/smoke_test.sql
-- 흐름: 기준정보 → 과제 → 문서/청크 → 성과카드 → 수요 → 임베딩 → 매칭 → 추천 →
--       검토 진입 가드 → 배정 → 의견 → 최종판정 권한 검사 → 최종판정 → 이력/KPI/평가
-- =============================================================================
\set QUIET on
BEGIN;
SET search_path = ax, public;
SET LOCAL hnsw.ef_search = 100;

-- 임의 단위벡터 생성기 (테스트 전용)
CREATE FUNCTION pg_temp.rand_vec(seed_vec vector DEFAULT NULL, noise real DEFAULT 1.0) RETURNS vector
LANGUAGE sql VOLATILE AS $$
    SELECT array_agg(COALESCE((seed_vec::real[])[i], 0) + noise * (random()::real - 0.5) ORDER BY i)::vector(1024)
    FROM generate_series(1, 1024) i
$$;

INSERT INTO department (id, dept_code, name) VALUES (1,'D-PLAN','과제기획팀'),(2,'D-C4I','지휘정찰기술팀'),(3,'D-COMM','무인미래통신기술팀');
INSERT INTO app_user (id, login_id, name, department_id, clearance_code) VALUES
 (1,'planner','기획담당',1,'RESTRICTED'),(2,'reviewer','부서검토자',2,'RESTRICTED'),
 (3,'expert','전문가',3,'INTERNAL'),(4,'lowuser','저등급사용자',2,'PUBLIC');
INSERT INTO user_role VALUES (1,'PLANNER',now(),NULL),(2,'DEPT_REVIEWER',now(),NULL),(3,'EXPERT',now(),NULL);
INSERT INTO organization (id, name, org_type) VALUES (1,'(주)테스트방산','COMPANY');
INSERT INTO company_profile (organization_id, is_defense_company, company_size) VALUES (1,true,'SME');
INSERT INTO program (id, program_code, name, program_type_code, purpose) VALUES
 (1,'P-LOC','부품국산화개발지원','PARTS_LOCALIZATION','수입 부품의 국산화'),
 (2,'P-CORE','핵심기술개발','CORE_TECH','미래 핵심기술 확보');
INSERT INTO weapon_system (id, system_code, name) VALUES (1,'WS-001','소형전술드론');
INSERT INTO item (id, item_no, name, is_part, is_imported) VALUES (1,'ITM-0001','저피탐 데이터링크 모뎀',true,true);

INSERT INTO project (id, project_no, title, program_id, lead_org_id, department_id, status_code, dev_stage_code, start_date, end_date)
VALUES (1,'PRJ-2022-001','소형 무인기용 항재밍 데이터링크 개발',2,1,3,'COMPLETED','PROTOTYPE','2022-01-01','2024-12-31');

INSERT INTO source_document (id, doc_type_code, title, project_id, owner_dept_id, source_system_code, external_ref, version_label, authored_at, security_code)
VALUES (1,'FINAL_REPORT','항재밍 데이터링크 결과보고서',1,3,'PMS','DOC-1','최종','2025-01-15','INTERNAL');
INSERT INTO document_section (id, document_id, section_no, heading, page_start, page_end, ordinal)
VALUES (1,1,'4.3','미해결 기술 및 후속 연구 필요사항',87,89,1);
INSERT INTO document_chunk (id, document_id, section_id, chunk_index, content, content_sha256, page_start, page_end, location)
VALUES (1,1,1,0,'광대역 재밍 환경에서 주파수 도약 동기 유지 시간이 목표 대비 부족하여 후속 연구가 필요함',
        repeat('a',64),88,88,'{"paragraph":2}');
INSERT INTO evidence (id, document_id, section_id, chunk_id, page_start, page_end, quote)
VALUES (1,1,1,1,88,88,'주파수 도약 동기 유지 시간이 목표 대비 부족');

INSERT INTO achievement_card (id, card_no, project_id, title, core_achievement, trl, dev_stage_code, status)
VALUES (1,'AC-2025-000001',1,'항재밍 FH 데이터링크','주파수 도약 기반 항재밍 데이터링크 시제 개발',5,'PROTOTYPE','PUBLISHED');
INSERT INTO card_technology (card_id, tech_name, principle, is_primary) VALUES (1,'주파수 도약 항재밍','고속 FH + 적응형 채널 선택',true);
INSERT INTO card_performance (id, card_id, metric_name, target_value, achieved_value, unit, is_achieved)
VALUES (1,1,'동기 유지 시간',10,6,'s',false);
INSERT INTO card_open_issue (id, card_id, issue_type, description, performance_id)
VALUES (1,1,'UNRESOLVED_TECH','광대역 재밍 환경에서 동기 유지 시간 부족',1);
INSERT INTO card_weapon_system (card_id, weapon_system_id) VALUES (1,1);
INSERT INTO card_field_evidence (card_id, target_table, target_id, field_name, evidence_id)
VALUES (1,'card_open_issue',1,'description',1);

-- 비교용 카드 2 (관련 낮음)
INSERT INTO project (id, project_no, title, department_id, status_code) VALUES (2,'PRJ-2021-007','전술 배터리 열관리',2,'COMPLETED');
INSERT INTO achievement_card (id, card_no, project_id, title, core_achievement, trl, status)
VALUES (2,'AC-2025-000002',2,'배터리 열관리','상변화물질 기반 열관리',6,'PUBLISHED');

INSERT INTO planning_demand (id, demand_no, title, tech_need, required_trl_min, required_trl_max, target_program_id, requesting_dept_id, owner_user_id, status)
VALUES (1,'DM-2026-001','광대역 재밍 대응 드론 데이터링크 고도화','광대역 재밍 하 링크 동기 유지',5,7,1,1,1,'OPEN');

-- 임베딩: 수요 TECH_NEED 를 카드1 OPEN_ISSUE 와 가깝게 생성
DO $$
DECLARE v1 vector; m smallint := (SELECT id FROM ax.embedding_model WHERE is_active);
BEGIN
    v1 := pg_temp.rand_vec();
    INSERT INTO ax.card_embedding (card_id, facet, source_table, source_id, model_id, source_text, source_sha256, card_revision, embedding)
    VALUES (1,'OPEN_ISSUE','card_open_issue',1,m,'광대역 재밍 환경에서 동기 유지 시간 부족',repeat('b',64),1,v1),
           (2,'OPEN_ISSUE',NULL,NULL,m,'열관리 미해결',repeat('c',64),1,pg_temp.rand_vec());
    INSERT INTO ax.demand_embedding (demand_id, facet, model_id, source_text, source_sha256, embedding)
    VALUES (1,'TECH_NEED',m,'광대역 재밍 하 링크 동기 유지',repeat('d',64),pg_temp.rand_vec(v1,0.2));
    INSERT INTO ax.chunk_embedding (chunk_id, model_id, embedding) VALUES (1,m,pg_temp.rand_vec(v1,0.3));
END $$;

\echo '--- match_cards(수요1, TECH_NEED → OPEN_ISSUE): 카드1 이 1위여야 함'
SELECT card_id, round(similarity::numeric,3) AS sim FROM match_cards(1,'TECH_NEED','OPEN_ISSUE',5);

-- 기획팀(1) 에 통신팀(3) 소관 자료 열람권 부여
INSERT INTO department_access_grant (grantee_dept_id, target_dept_id, max_security_code) VALUES (1,3,'RESTRICTED');

\echo '--- search_chunks: 사용자1(타부서 열람권 있음) 1건, 사용자4(공개등급) 0건, 사용자2(권한 없는 타부서) 0건'
SELECT 'user1' u, count(*) FROM search_chunks((SELECT embedding FROM demand_embedding WHERE demand_id=1), 1, 5)
UNION ALL
SELECT 'user4', count(*) FROM search_chunks((SELECT embedding FROM demand_embedding WHERE demand_id=1), 4, 5)
UNION ALL
SELECT 'user2', count(*) FROM search_chunks((SELECT embedding FROM demand_embedding WHERE demand_id=1), 2, 5);

-- 매칭 실행 + 추천 생성
SET LOCAL app.current_user_id = '1';
INSERT INTO match_run (id, run_type, demand_id, model_id, rule_snapshot, requested_by, status)
SELECT 1,'DEMAND_TO_CARD',1,(SELECT id FROM embedding_model WHERE is_active),
       (SELECT jsonb_object_agg(linkage_type_code, weights) FROM linkage_rule WHERE is_active),1,'SUCCEEDED';
INSERT INTO recommendation (id, match_run_id, demand_id, linkage_type_code, rank, total_score, confidence, rationale, development_needs)
VALUES (1,1,1,'FOLLOW_UP',1,0.82,0.75,'카드1 미해결 기술(동기 유지 시간 부족)이 수요 기술과 직결','광대역 재밍 대응 동기 알고리즘 개선'),
       (2,1,1,'CONVERGENCE',2,0.41,0.30,'열관리 결합 가능성','-');
INSERT INTO recommendation_source_card (recommendation_id, card_id, open_issue_id) VALUES (1,1,1);
INSERT INTO recommendation_source_card (recommendation_id, card_id) VALUES (2,1);
INSERT INTO recommendation_score VALUES
 (1,'TECH',0.91,0.45,'cosine:OPEN_ISSUE↔TECH_NEED','{}'),(1,'TRL',0.80,0.20,'rule:trl_gap','{}');
INSERT INTO recommendation_department VALUES (1,2,'OWNER',0.7,'통신 소관'),(1,3,'COLLABORATOR',0.5,'원과제 수행부서');

\echo '--- 가드: 근거 없는 추천 1 을 검토 배정 → 오류 기대'
DO $$ BEGIN
    INSERT INTO ax.review_assignment (recommendation_id, review_role, assignee_dept_id) VALUES (1,'DEPT_OWNER',2);
    RAISE EXCEPTION 'FAIL: 가드 미동작';
EXCEPTION WHEN check_violation THEN RAISE NOTICE 'OK: %', SQLERRM; END $$;

\echo '--- 가드: 융합형 추천 2 (카드 1개) 검토 배정 → 오류 기대'
INSERT INTO recommendation_evidence (recommendation_id, evidence_id, side) VALUES (2,1,'SOURCE_CARD');
DO $$ BEGIN
    INSERT INTO ax.review_assignment (recommendation_id, review_role, assignee_dept_id) VALUES (2,'DEPT_OWNER',2);
    RAISE EXCEPTION 'FAIL: 가드 미동작';
EXCEPTION WHEN check_violation THEN RAISE NOTICE 'OK: %', SQLERRM; END $$;

-- 근거 연결 후 배정
INSERT INTO recommendation_evidence (recommendation_id, evidence_id, side, criterion, relevance_score, explanation)
VALUES (1,1,'SOURCE_CARD','TECH',0.88,'원과제 결과보고서 4.3절: 미해결 기술 명시');
INSERT INTO review_assignment (id, recommendation_id, review_role, assignee_user_id, assigned_by) VALUES
 (1,1,'EXPERT',3,1),(2,1,'DEPT_OWNER',2,1);

-- 전문가 의견 (비최종)
SET LOCAL app.current_user_id = '3';
INSERT INTO review_decision (recommendation_id, assignment_id, reviewer_id, decision_code, opinion, relevance_rating, evidence_adequacy, dev_needs_accuracy)
VALUES (1,1,3,'ADOPT','후속형 적절',5,4,'CORRECT');

\echo '--- 권한: 전문가(EXPERT) 가 최종판정 → 오류 기대'
DO $$ BEGIN
    INSERT INTO ax.review_decision (recommendation_id, reviewer_id, decision_code, is_final) VALUES (1,3,'ADOPT',true);
    RAISE EXCEPTION 'FAIL: 권한검사 미동작';
EXCEPTION WHEN insufficient_privilege THEN RAISE NOTICE 'OK: %', SQLERRM; END $$;

-- 담당부서 최종판정 (연계유형 수정 포함)
SET LOCAL app.current_user_id = '2';
INSERT INTO review_decision (recommendation_id, assignment_id, reviewer_id, decision_code, is_final, linkage_type_override, opinion)
VALUES (1,2,2,'ADOPT',true,'ADVANCEMENT','미해결 기술 해결 + 성능 향상 성격이 강해 고도화형으로 조정');

\echo '--- 추가 전용: review_decision UPDATE → 오류 기대'
DO $$ BEGIN
    UPDATE ax.review_decision SET opinion = 'x';
    RAISE EXCEPTION 'FAIL: 추가 전용 미동작';
EXCEPTION WHEN insufficient_privilege THEN RAISE NOTICE 'OK: %', SQLERRM; END $$;

\echo '--- 추천 상태 이력'
SELECT recommendation_id, from_status, to_status, changed_by FROM recommendation_status_history WHERE recommendation_id = 1 ORDER BY id;

\echo '--- 추천 개요'
SELECT recommendation_id, linkage_type_name, final_linkage_type_code, status, final_decision_code, owner_department, evidence_count
FROM v_recommendation_overview WHERE recommendation_id = 1;

\echo '--- 근거 상세 (문서·조항·페이지)'
SELECT document_title, section_no, section_heading, page_start, quote FROM v_recommendation_evidence WHERE recommendation_id = 1;

\echo '--- 감사 로그 (recommendation)'
SELECT table_name, row_pk, action, actor_user_id, changed_fields FROM audit_log
WHERE table_name = 'recommendation' ORDER BY id;

\echo '--- KPI'
SELECT * FROM v_kpi_recommendation;

-- PoC 평가: 정답 카드1 이 Top-5 에 포함되는지
INSERT INTO eval_case (id, name, case_type, query_type, demand_id) VALUES (1,'드론 데이터링크 사례','EXPERT_PANEL','DEMAND',1);
INSERT INTO eval_ground_truth (case_id, expected_card_id, linkage_type_code, importance) VALUES (1,1,'FOLLOW_UP','MAJOR');
INSERT INTO eval_run (id, name, top_k) VALUES (1,'smoke',5);
INSERT INTO eval_run_case VALUES (1,1,1);
INSERT INTO work_time_measurement (task_type, method, minutes) VALUES ('RESEARCH','MANUAL',300),('RESEARCH','AX',75);
\echo '--- 평가 KPI'
SELECT * FROM v_kpi_eval;
SELECT * FROM v_kpi_work_time;

\echo '--- 계획 확인: 패싯 부분 HNSW 인덱스 사용'
SET LOCAL enable_seqscan = off;
EXPLAIN (COSTS OFF)
SELECT card_id FROM card_embedding WHERE facet = 'OPEN_ISSUE'
ORDER BY embedding <=> (SELECT embedding FROM demand_embedding LIMIT 1) LIMIT 5;

\echo '--- Navigator: 사업자번호로 기업 넣고 조회 (0019·0020)'
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

\echo '--- Navigator: 공고·자격요건 (0021)'
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

\echo '--- Navigator: 매칭 실행·판정·근거·보완질문 답 (0022)'
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
