-- 0027: 공고에서 자주 거르는 조건 (결격사유·방산 실적·수출 실적)
--   NULL = 아직 모름 → 판정은 '확인 필요'
SET search_path = ax, public;

ALTER TABLE ax.company_profile
    ADD COLUMN tax_delinquent      boolean,                        -- 국세·지방세 체납
    ADD COLUMN insolvent           boolean,                        -- 부도·자본잠식
    ADD COLUMN rnd_restricted      boolean,                        -- 국가 R&D 참여제한
    ADD COLUMN defense_goods       boolean,                        -- 방산물자 생산
    ADD COLUMN military_supply_krw bigint CHECK (military_supply_krw >= 0),  -- 최근 3년 군 납품(조달) 실적 합계
    ADD COLUMN export_krw          bigint CHECK (export_krw >= 0),           -- 최근 연도 수출액
    ADD COLUMN export_year         smallint;

INSERT INTO ax.code_requirement_type (code, name_ko, rule_example, description, sort_order) VALUES
 ('NO_DISQUALIFICATION', '결격사유 없음', '{"checks":["TAX_DELINQUENT","INSOLVENT","RND_RESTRICTED"]}',
  '체납·부도/자본잠식·국가 R&D 참여제한 중 나열한 것에 해당하지 않을 것', 13),
 ('DEFENSE_SUPPLY', '방산 실적', '{"defense_goods":true,"min_supply_krw":100000000}',
  '방산물자 생산 여부 / 최근 3년 군 납품 실적 하한 (원). 둘 중 준 것만 확인', 14),
 ('EXPORT', '수출 실적', '{"min_krw":1}', '최근 연도 수출액 하한 (원)', 15)
ON CONFLICT (code) DO NOTHING;
