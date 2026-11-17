-- =============================================================================
-- 0036: 이어달리기 후보 검토표 · 통합기획 자료 초안 · 통합기획 회의 결정 (0013 표를 쓰기 위한 보강)
--   relay_review_sheet   생성 조건(criteria)·보안등급·확정 정보 칸 추가
--   planning_draft       보안등급 칸 추가 (검토표에서 만든 초안은 검토표 등급을 따른다)
--   meeting_decision     결정을 기록한 사람 칸 추가
-- 규칙
--   - 검토표의 보안등급은 실린 추천(수요·출처 성과카드)의 가장 높은 등급보다 낮을 수 없다.
--     검토표 항목은 생성 시점 사본(snapshot)이라, 나중에 등급이 바뀌어도 사본을 통해 새지 않게 한다.
--   - 확정(FINALIZED)된 검토표는 항목을 바꿀 수 없다 (회의자료 재현).
--   - 검토표·회의 결정은 감사 대상.
-- =============================================================================
SET search_path = ax, public;

ALTER TABLE ax.relay_review_sheet
    ADD COLUMN criteria      jsonb NOT NULL DEFAULT '{}'::jsonb,   -- 생성 조건 (범위·부서·수요·최대 건수)
    ADD COLUMN security_code text  NOT NULL DEFAULT 'INTERNAL' REFERENCES ax.code_security_level(code),
    ADD COLUMN finalized_by  bigint REFERENCES ax.app_user(id),
    ADD COLUMN finalized_at  timestamptz;
CREATE INDEX relay_review_sheet_dept ON ax.relay_review_sheet(department_id);
CREATE INDEX relay_review_sheet_meeting ON ax.relay_review_sheet(meeting_id);

ALTER TABLE ax.planning_draft
    ADD COLUMN security_code text NOT NULL DEFAULT 'INTERNAL' REFERENCES ax.code_security_level(code);
CREATE INDEX planning_draft_sheet ON ax.planning_draft(sheet_id);

ALTER TABLE ax.meeting_decision
    ADD COLUMN decided_by bigint REFERENCES ax.app_user(id);
CREATE INDEX meeting_decision_meeting ON ax.meeting_decision(meeting_id);

-- 검토표 항목: 추천 등급보다 낮은 검토표에 실을 수 없고, 확정된 검토표는 바꿀 수 없다
CREATE OR REPLACE FUNCTION ax.check_review_sheet_item() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_sheet_id   bigint := COALESCE(NEW.sheet_id, OLD.sheet_id);
    v_status     text;
    v_sheet_rank smallint;
    v_rec_rank   smallint;
BEGIN
    SELECT s.status, l.level_rank INTO v_status, v_sheet_rank
      FROM ax.relay_review_sheet s JOIN ax.code_security_level l ON l.code = s.security_code
     WHERE s.id = v_sheet_id;
    IF v_status IS DISTINCT FROM 'DRAFT' AND v_status IS NOT NULL THEN
        RAISE EXCEPTION '확정된 검토표 % 의 항목은 바꿀 수 없습니다', v_sheet_id USING ERRCODE = 'check_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    SELECT GREATEST(
             COALESCE((SELECT dl.level_rank FROM ax.recommendation r
                         JOIN ax.planning_demand d ON d.id = r.demand_id
                         JOIN ax.code_security_level dl ON dl.code = d.security_code
                        WHERE r.id = NEW.recommendation_id), 0),
             COALESCE((SELECT max(cl.level_rank) FROM ax.recommendation_source_card rsc
                         JOIN ax.achievement_card ac ON ac.id = rsc.card_id
                         JOIN ax.code_security_level cl ON cl.code = ac.security_code
                        WHERE rsc.recommendation_id = NEW.recommendation_id), 0))
      INTO v_rec_rank;
    IF v_rec_rank > v_sheet_rank THEN
        RAISE EXCEPTION '추천 % 의 보안등급이 검토표 % 의 등급보다 높습니다', NEW.recommendation_id, v_sheet_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_review_sheet_item_check BEFORE INSERT OR UPDATE OR DELETE ON ax.relay_review_sheet_item
    FOR EACH ROW EXECUTE FUNCTION ax.check_review_sheet_item();

-- 확정된 검토표는 되돌리거나 등급을 낮출 수 없다 (보관 처리만 가능)
CREATE OR REPLACE FUNCTION ax.check_review_sheet_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status = 'FINALIZED' AND NEW.status = 'DRAFT' THEN
        RAISE EXCEPTION '확정된 검토표 % 는 초안으로 되돌릴 수 없습니다', OLD.id USING ERRCODE = 'check_violation';
    END IF;
    IF (SELECT level_rank FROM ax.code_security_level WHERE code = NEW.security_code)
       < (SELECT level_rank FROM ax.code_security_level WHERE code = OLD.security_code) THEN
        RAISE EXCEPTION '검토표 % 의 보안등급을 낮출 수 없습니다', OLD.id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_review_sheet_update_check BEFORE UPDATE ON ax.relay_review_sheet
    FOR EACH ROW EXECUTE FUNCTION ax.check_review_sheet_update();

CREATE TRIGGER trg_relay_review_sheet_audit AFTER INSERT OR UPDATE OR DELETE ON ax.relay_review_sheet
    FOR EACH ROW EXECUTE FUNCTION ax.audit_row();
CREATE TRIGGER trg_meeting_decision_audit AFTER INSERT OR UPDATE OR DELETE ON ax.meeting_decision
    FOR EACH ROW EXECUTE FUNCTION ax.audit_row();
CREATE TRIGGER trg_planning_meeting_audit AFTER INSERT OR UPDATE OR DELETE ON ax.planning_meeting
    FOR EACH ROW EXECUTE FUNCTION ax.audit_row();
