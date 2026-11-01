-- =============================================================================
-- 0018: 권한·감사 보강 (2026-11 최종 점검 결과)
--   1) ax.can_view_recommendation: 추천을 보려면 수요와 출처 성과카드의 보안등급을 모두 열람할 수 있어야 한다.
--      (카드·수요 API 는 등급을 검사했지만 추천·매칭 실행·이력 API 로는 제목·연계이유가 그대로 보였다)
--   2) 최종판정: DEPT_REVIEWER 는 자기 부서가 소관(OWNER)이거나 자기/자기 부서에 담당부서 배정이 있을 때만.
--      (전에는 어느 부서 검토자든 모든 추천을 최종판정할 수 있었다) ADMIN 은 예외.
--   3) 감사 대상 추가: app_user(보안등급·활성 변경), review_comment, recommendation_evidence.
--   4) 추가 전용 테이블 TRUNCATE 차단 (행 트리거는 TRUNCATE 에 걸리지 않음).
-- =============================================================================
SET search_path = ax, public;

CREATE OR REPLACE FUNCTION ax.can_view_recommendation(p_user_id bigint, p_recommendation_id bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT EXISTS (
        SELECT 1
          FROM ax.recommendation r
          JOIN ax.app_user u             ON u.id = p_user_id AND u.is_active
          JOIN ax.code_security_level ul ON ul.code = u.clearance_code
         WHERE r.id = p_recommendation_id
           AND NOT EXISTS (SELECT 1 FROM ax.planning_demand d
                             JOIN ax.code_security_level dl ON dl.code = d.security_code
                            WHERE d.id = r.demand_id AND dl.level_rank > ul.level_rank)
           AND NOT EXISTS (SELECT 1 FROM ax.recommendation_source_card rsc
                             JOIN ax.achievement_card ac ON ac.id = rsc.card_id
                             JOIN ax.code_security_level cl ON cl.code = ac.security_code
                            WHERE rsc.recommendation_id = r.id AND cl.level_rank > ul.level_rank)
    )
$$;
COMMENT ON FUNCTION ax.can_view_recommendation(bigint, bigint) IS
  '사용자 보안등급 ≥ 수요 등급 그리고 ≥ 모든 출처 성과카드 등급이면 추천 열람 가능';

-- 판정 입력 검증 (0012 대체): 최종판정 부서 범위 검사 추가
CREATE OR REPLACE FUNCTION ax.validate_review_decision() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_status text;
    v_dept   bigint;
BEGIN
    SELECT status INTO v_status FROM ax.recommendation WHERE id = NEW.recommendation_id;
    IF v_status IN ('GENERATED','WITHDRAWN') THEN
        RAISE EXCEPTION '추천 % 은(는) 검토 배정 전이거나 철회된 상태(%)입니다', NEW.recommendation_id, v_status
            USING ERRCODE = 'check_violation';
    END IF;

    IF NEW.is_final THEN
        IF NOT EXISTS (SELECT 1 FROM ax.code_review_decision WHERE code = NEW.decision_code AND is_terminal) THEN
            RAISE EXCEPTION '판정 % 은(는) 최종판정으로 사용할 수 없습니다', NEW.decision_code
                USING ERRCODE = 'check_violation';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM ax.user_role
                       WHERE user_id = NEW.reviewer_id AND role_code IN ('DEPT_REVIEWER','ADMIN')) THEN
            RAISE EXCEPTION '사용자 % 은(는) 최종판정 권한(DEPT_REVIEWER)이 없습니다', NEW.reviewer_id
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM ax.user_role WHERE user_id = NEW.reviewer_id AND role_code = 'ADMIN') THEN
            SELECT department_id INTO v_dept FROM ax.app_user WHERE id = NEW.reviewer_id;
            IF NOT EXISTS (SELECT 1 FROM ax.recommendation_department rd
                            WHERE rd.recommendation_id = NEW.recommendation_id AND rd.role = 'OWNER'
                              AND rd.department_id = v_dept)
               AND NOT EXISTS (SELECT 1 FROM ax.review_assignment ra
                                WHERE ra.recommendation_id = NEW.recommendation_id AND ra.review_role = 'DEPT_OWNER'
                                  AND ra.status <> 'CANCELLED'
                                  AND (ra.assignee_user_id = NEW.reviewer_id OR ra.assignee_dept_id = v_dept)) THEN
                RAISE EXCEPTION '사용자 % 은(는) 추천 % 의 소관부서 검토자가 아닙니다 (최종판정 불가)',
                    NEW.reviewer_id, NEW.recommendation_id
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END $$;

-- 감사 대상 추가
CREATE TRIGGER trg_app_user_audit AFTER INSERT OR UPDATE OR DELETE ON ax.app_user
    FOR EACH ROW EXECUTE FUNCTION ax.audit_row();
CREATE TRIGGER trg_review_comment_audit AFTER INSERT OR UPDATE OR DELETE ON ax.review_comment
    FOR EACH ROW EXECUTE FUNCTION ax.audit_row();
CREATE TRIGGER trg_recommendation_evidence_audit AFTER INSERT OR UPDATE OR DELETE ON ax.recommendation_evidence
    FOR EACH ROW EXECUTE FUNCTION ax.audit_row();

-- 추가 전용 테이블 TRUNCATE 차단 (forbid_mutation 은 TRUNCATE 에서 항상 예외)
CREATE TRIGGER trg_review_decision_no_truncate BEFORE TRUNCATE ON ax.review_decision
    FOR EACH STATEMENT EXECUTE FUNCTION ax.forbid_mutation();
CREATE TRIGGER trg_status_history_no_truncate BEFORE TRUNCATE ON ax.recommendation_status_history
    FOR EACH STATEMENT EXECUTE FUNCTION ax.forbid_mutation();
CREATE TRIGGER trg_audit_log_no_truncate BEFORE TRUNCATE ON ax.audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION ax.forbid_mutation();
