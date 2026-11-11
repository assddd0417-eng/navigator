-- =============================================================================
-- 0027: 기관 포트폴리오 (전국 R&D 성과 ↔ 해외 수요 갭 → 정책·예산 기획 후보)
--   planning_demand.origin_gap_finding_id   확정된 갭에서 넘겨 만든 신규 기획수요
-- 규칙
--   - 갭 하나에서 기획수요는 하나만 만든다.
--   - 확정(CONFIRMED)된 갭만 기획수요로 넘길 수 있다 (검수 전·기각·대체된 갭은 안 됨).
--   - 기획수요의 보안등급은 넘겨받은 갭의 보안등급보다 낮을 수 없다.
--   포트폴리오 화면의 집계는 기존 표(성과 카드·해외 수요·갭)를 조회만 한다 (새 표 없음).
-- =============================================================================
SET search_path = ax, public;

ALTER TABLE ax.planning_demand
    ADD COLUMN origin_gap_finding_id bigint REFERENCES ax.gap_finding(id) ON DELETE SET NULL;
CREATE UNIQUE INDEX planning_demand_origin_gap ON ax.planning_demand(origin_gap_finding_id)
    WHERE origin_gap_finding_id IS NOT NULL;

CREATE OR REPLACE FUNCTION ax.check_demand_from_gap() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_status text;
    v_gap_rank smallint;
    v_demand_rank smallint;
BEGIN
    IF NEW.origin_gap_finding_id IS NULL THEN
        RETURN NEW;
    END IF;
    SELECT f.status, l.level_rank INTO v_status, v_gap_rank
      FROM ax.gap_finding f JOIN ax.code_security_level l ON l.code = f.security_code
     WHERE f.id = NEW.origin_gap_finding_id;
    IF TG_OP = 'INSERT' OR NEW.origin_gap_finding_id IS DISTINCT FROM OLD.origin_gap_finding_id THEN
        IF v_status IS DISTINCT FROM 'CONFIRMED' THEN
            RAISE EXCEPTION '갭 % 은(는) 확정되지 않아(%) 기획수요로 넘길 수 없습니다', NEW.origin_gap_finding_id, v_status
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    SELECT level_rank INTO v_demand_rank FROM ax.code_security_level WHERE code = NEW.security_code;
    IF v_demand_rank < v_gap_rank THEN
        RAISE EXCEPTION '기획수요의 보안등급이 근거 갭(%)의 보안등급보다 낮습니다', NEW.origin_gap_finding_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_planning_demand_from_gap
    BEFORE INSERT OR UPDATE OF origin_gap_finding_id, security_code ON ax.planning_demand
    FOR EACH ROW EXECUTE FUNCTION ax.check_demand_from_gap();
