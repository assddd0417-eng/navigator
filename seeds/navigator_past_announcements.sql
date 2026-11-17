-- 참여할 수 있었던 사업 시연용 마감 공고 (가상). navigator_announcements.sql 다음에 적용.
--   106 = 101(전술통신 부품국산화)의 이전 회차, 2025-12-15 마감. 같은 series_key 로 묶어 "올해 공고 접수중"을 보여 준다.
-- 재실행 가능: psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f seeds/navigator_past_announcements.sql
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL search_path = ax, public;

INSERT INTO announcement (id, announcement_no, title, agency_name, domain, program_id, summary, target_desc,
                          support_amount_krw, support_period_months, receipt_start, receipt_end, source_kind,
                          status, series_key) OVERRIDING SYSTEM VALUE
SELECT 106, 'NAV-2025-106', '2026년 전술통신 부품국산화 개발지원 사업 공고(가상)', a.agency_name, a.domain, a.program_id,
       a.summary, a.target_desc, a.support_amount_krw, a.support_period_months, '2025-11-03', '2025-12-15',
       'MANUAL', 'PUBLISHED', 'nav-tactical-comm-localization'
  FROM announcement a WHERE a.id = 101
ON CONFLICT (id) DO UPDATE SET
  announcement_no = EXCLUDED.announcement_no, title = EXCLUDED.title, agency_name = EXCLUDED.agency_name,
  domain = EXCLUDED.domain, program_id = EXCLUDED.program_id, summary = EXCLUDED.summary,
  target_desc = EXCLUDED.target_desc, support_amount_krw = EXCLUDED.support_amount_krw,
  support_period_months = EXCLUDED.support_period_months, receipt_start = EXCLUDED.receipt_start,
  receipt_end = EXCLUDED.receipt_end, status = EXCLUDED.status, series_key = EXCLUDED.series_key;

UPDATE announcement SET series_key = 'nav-tactical-comm-localization' WHERE id = 101;

DELETE FROM announcement_requirement WHERE announcement_id = 106;
DELETE FROM announcement_tech_need   WHERE announcement_id = 106;
DELETE FROM announcement_embedding   WHERE announcement_id = 106;

-- 요건·요구기술은 101 과 같게
INSERT INTO announcement_requirement (announcement_id, req_type_code, rule, is_mandatory, description,
                                      source_quote, source_page, sort_order)
SELECT 106, req_type_code, rule, is_mandatory, description, source_quote, source_page, sort_order
  FROM announcement_requirement WHERE announcement_id = 101;
INSERT INTO announcement_tech_need (announcement_id, tech_name, description, ipc_codes, is_core, sort_order)
SELECT 106, tech_name, description, ipc_codes, is_core, sort_order
  FROM announcement_tech_need WHERE announcement_id = 101;

DO $$ BEGIN
  PERFORM setval(pg_get_serial_sequence('ax.announcement', 'id'), GREATEST((SELECT max(id) FROM ax.announcement), 10));
END $$;

COMMIT;

SELECT id, announcement_no, title, receipt_state, series_key FROM ax.v_announcement WHERE id IN (101, 106) ORDER BY id;
