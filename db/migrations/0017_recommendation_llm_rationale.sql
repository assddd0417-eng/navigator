-- =============================================================================
-- 0017: LLM 연계이유 문장
--   rationale     : 규칙 템플릿 문장 (항상 존재, 누구에게나 표시 가능)
--   rationale_llm : 원문 근거·점수를 입력으로 LLM 이 쓴 문장 (RATIONALE_GENERATOR=llm, 검증 통과 시)
--   rationale_meta: {"generator","status":"OK|FALLBACK","document_ids","evidence_ids","error"}
--   LLM 문장에는 근거 문서 내용이 녹아 있으므로, document_ids 를 모두 열람할 수 있는
--   사용자에게만 rationale_llm 을 보여 주고 나머지에게는 템플릿 문장을 보여 준다.
-- =============================================================================
SET search_path = ax, public;

ALTER TABLE ax.recommendation
    ADD COLUMN IF NOT EXISTS rationale_llm  text,
    ADD COLUMN IF NOT EXISTS rationale_meta jsonb NOT NULL DEFAULT '{}'::jsonb;
COMMENT ON COLUMN ax.recommendation.rationale_llm IS 'LLM 생성 연계이유 (근거 검증 통과분). 표시는 ax.rationale_for_user 로';
COMMENT ON COLUMN ax.recommendation.rationale_meta IS 'LLM 연계이유 생성 기록: 생성기·성공/대체·입력 근거 문서';

-- 사용자에게 보여 줄 연계이유와 출처 (LLM / TEMPLATE / TEMPLATE_RESTRICTED)
CREATE OR REPLACE FUNCTION ax.rationale_for_user(p_user_id bigint, p_recommendation_id bigint)
RETURNS TABLE (rationale text, rationale_source text) LANGUAGE sql STABLE AS $$
    SELECT CASE WHEN v.llm_ok THEN r.rationale_llm ELSE r.rationale END,
           CASE WHEN v.llm_ok THEN 'LLM'
                WHEN r.rationale_llm IS NOT NULL THEN 'TEMPLATE_RESTRICTED'
                ELSE 'TEMPLATE' END
      FROM ax.recommendation r,
           LATERAL (SELECT r.rationale_llm IS NOT NULL AND NOT EXISTS (
                        SELECT 1 FROM jsonb_array_elements_text(COALESCE(r.rationale_meta->'document_ids', '[]'::jsonb)) d
                         WHERE NOT ax.can_read_document(p_user_id, d::bigint)) AS llm_ok) v
     WHERE r.id = p_recommendation_id
$$;
