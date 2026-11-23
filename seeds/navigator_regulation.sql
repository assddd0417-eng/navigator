-- 운영규정·지침 (가상). navigator_consult.sql 다음에 실행
--   공통운영규정: 참여제한 (체납·부도·참여제한·부정당제재), 중복지원 제한 1년. 모든 공고 자격검토에 더해진다
--   사업별: 방산 중소기업 컨설팅 지원 운영지침
-- 조문 벡터는 처음 검색할 때 만든다
-- 재실행 가능: psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f seeds/navigator_regulation.sql
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL search_path = ax, public;

DELETE FROM regulation WHERE title IN ('방산 지원사업 공통운영규정(가상)', '방산 중소기업 컨설팅 지원 운영지침(가상)');

WITH g AS (
  INSERT INTO regulation (title, kind, owner_dept_id, version_label, effective_on, confirmed_at, confirmed_by, created_by)
  VALUES ('방산 지원사업 공통운영규정(가상)', 'COMMON', 2, '2026.1', '2026-01-01', now(), 3, 3) RETURNING id)
INSERT INTO regulation_article (regulation_id, sort_order, article_no, title, body, checks, within_years)
SELECT g.id, v.ord, v.no, v.title, v.body, v.checks, v.years FROM g, (VALUES
  (1, '제1조', '목적', '이 규정은 방산 지원사업의 신청·선정·관리에 공통으로 적용할 사항을 정한다.', '{}'::text[], NULL::smallint),
  (2, '제7조', '참여제한', '다음 각 호의 기업은 지원사업에 신청할 수 없다. 1. 국세 또는 지방세를 체납한 기업 2. 부도, 파산 또는 자본잠식 상태인 기업 3. 국가연구개발사업 참여제한 기간 중인 기업 4. 부정당업자 제재 기간 중인 기업',
   '{TAX_DELINQUENT,INSOLVENT,RND_RESTRICTED,PROCUREMENT_SANCTIONED}', NULL),
  (3, '제8조', '중복지원 제한', '최근 1년 안에 동일 사업의 지원을 받았거나 수행 중인 기업은 같은 사업에 신청할 수 없다. 다만 사업별 운영지침에서 따로 정한 경우에는 그에 따른다.',
   '{DUPLICATE}', 1),
  (4, '제12조', '신청서류', '신청기업은 사업계획서, 중소기업확인서, 국세·지방세 납세증명서를 제출한다. 해당 기업은 인증서 사본을 함께 제출한다.', '{}', NULL),
  (5, '제15조', '협약 포기', '선정 후 정당한 사유 없이 협약을 포기한 기업은 포기일로부터 1년간 감점한다.', '{}', NULL)
) AS v(ord, no, title, body, checks, years);

WITH g AS (
  INSERT INTO regulation (title, kind, program_id, owner_dept_id, version_label, effective_on, created_by)
  VALUES ('방산 중소기업 컨설팅 지원 운영지침(가상)', 'PROGRAM', (SELECT id FROM program WHERE program_code = 'P-CONSULT'),
          2, '2026.1', '2026-02-01', 3) RETURNING id)
INSERT INTO regulation_article (regulation_id, sort_order, article_no, title, body, checks, within_years)
SELECT g.id, v.ord, v.no, v.title, v.body, v.checks, v.years FROM g, (VALUES
  (1, '제3조', '지원대상', '방산분야에 진출하려는 중소기업과 방산 협력업체를 대상으로 한다.', '{}'::text[], NULL::smallint),
  (2, '제5조', '기업부담', '컨설팅 비용의 25%는 기업이 부담한다. 다만 창업기업은 15%로 한다.', '{}', NULL),
  (3, '제6조', '평가', '재무상황, 기술성, 컨설팅 목적성, 수행방안과 기대효과를 평가한다. 상담 단계에서는 신청서 기반 항목을 평가하지 않는다.', '{}', NULL)
) AS v(ord, no, title, body, checks, years);

COMMIT;
