-- =============================================================================
-- 0037: 연계 실행 결과와 순환 구조 (기존 성과 → 신규 과제 → 성과 축적 → 다시 기존 성과)
--   linkage_execution  회의 결정 연결·결과 메모·보안등급·수정일 칸 추가 (0013 표 보강)
--   eval_case          실제 연계 사례에서 만든 검증 케이스 표시(origin_execution_id)
-- 규칙
--   - 추천에서 나온 실행은 담당부서가 '채택'으로 최종 판정한 추천만 기록할 수 있다.
--   - 실행의 출처 성과는 그 추천의 출처 성과 중 하나여야 한다.
--   - 실행으로 이어진 과제는 출처 성과의 과제와 달라야 한다.
--   - 보안등급은 출처 성과의 등급보다 낮을 수 없다.
--   - 실행 결과는 감사 대상.
-- =============================================================================
SET search_path = ax, public;

ALTER TABLE ax.linkage_execution
    ADD COLUMN meeting_decision_id bigint REFERENCES ax.meeting_decision(id) ON DELETE SET NULL,
    ADD COLUMN result_note   text,                                  -- 결과 요약 (과제화 규모·사업화 실적 등)
    ADD COLUMN security_code text NOT NULL DEFAULT 'INTERNAL' REFERENCES ax.code_security_level(code),
    ADD COLUMN updated_at    timestamptz NOT NULL DEFAULT now();
CREATE TRIGGER trg_linkage_execution_updated BEFORE UPDATE ON ax.linkage_execution
    FOR EACH ROW EXECUTE FUNCTION ax.set_updated_at();
CREATE INDEX linkage_execution_project ON ax.linkage_execution(resulting_project_id);
CREATE INDEX linkage_execution_status ON ax.linkage_execution(status);

-- 실제 연계 사례 → 검증 케이스 (같은 실행으로 두 번 만들지 않음)
ALTER TABLE ax.eval_case
    ADD COLUMN origin_execution_id bigint REFERENCES ax.linkage_execution(id) ON DELETE SET NULL;
CREATE UNIQUE INDEX eval_case_origin_execution ON ax.eval_case(origin_execution_id)
    WHERE origin_execution_id IS NOT NULL;

CREATE OR REPLACE FUNCTION ax.check_linkage_execution() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_decision  text;
    v_card_proj bigint;
    v_card_rank smallint;
BEGIN
    SELECT ac.project_id, l.level_rank INTO v_card_proj, v_card_rank
      FROM ax.achievement_card ac JOIN ax.code_security_level l ON l.code = ac.security_code
     WHERE ac.id = NEW.source_card_id;

    IF NEW.recommendation_id IS NOT NULL
       AND (TG_OP = 'INSERT' OR NEW.recommendation_id IS DISTINCT FROM OLD.recommendation_id
            OR NEW.source_card_id IS DISTINCT FROM OLD.source_card_id) THEN
        SELECT final_decision_code INTO v_decision FROM ax.recommendation WHERE id = NEW.recommendation_id;
        IF v_decision IS DISTINCT FROM 'ADOPT' THEN
            RAISE EXCEPTION '추천 % 은(는) 담당부서가 채택한 추천이 아닙니다 (지금 판정: %)',
                NEW.recommendation_id, COALESCE(v_decision, '없음') USING ERRCODE = 'check_violation';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM ax.recommendation_source_card
                        WHERE recommendation_id = NEW.recommendation_id AND card_id = NEW.source_card_id) THEN
            RAISE EXCEPTION '성과카드 % 은(는) 추천 % 의 출처 성과가 아닙니다', NEW.source_card_id, NEW.recommendation_id
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;

    IF NEW.resulting_project_id IS NOT NULL AND NEW.resulting_project_id = v_card_proj THEN
        RAISE EXCEPTION '이어진 과제가 출처 성과의 과제와 같습니다' USING ERRCODE = 'check_violation';
    END IF;

    IF (SELECT level_rank FROM ax.code_security_level WHERE code = NEW.security_code) < v_card_rank THEN
        RAISE EXCEPTION '실행 결과의 보안등급이 출처 성과의 등급보다 낮습니다' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_linkage_execution_check BEFORE INSERT OR UPDATE ON ax.linkage_execution
    FOR EACH ROW EXECUTE FUNCTION ax.check_linkage_execution();

CREATE TRIGGER trg_linkage_execution_audit AFTER INSERT OR UPDATE OR DELETE ON ax.linkage_execution
    FOR EACH ROW EXECUTE FUNCTION ax.audit_row();
