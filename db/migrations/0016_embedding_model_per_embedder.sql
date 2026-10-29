-- =============================================================================
-- 0016: 임베더별 모델 행 분리 (hash 테스트 벡터와 BGE-M3 벡터가 섞이지 않게)
--
--   0010 은 활성 모델을 'BAAI/bge-m3' 하나만 등록했고, 기본 임베더(EMBEDDER=hash)가 만든
--   테스트용 벡터도 그 모델 ID 로 저장되었다. 이 상태에서 EMBEDDER=bge_m3 로 바꾸면
--   텍스트 sha256 이 같아 재임베딩이 생략되고, 의미 없는 hash 벡터와 BGE-M3 벡터가 한 공간에서 비교된다.
--
--   - 해시 임베더 전용 모델 행 'relay-ax/hash-ngram' 을 추가한다.
--   - 0016 이전 벡터는 모두 hash 임베더가 만든 것으로 보고 그 행으로 옮긴다
--     (bge 선택 의존성 없이는 BGE-M3 를 쓸 수 없었다. 혹시 BGE-M3 로 만든 벡터가 있었다면
--      서버를 EMBEDDER=bge_m3 로 띄운 뒤 `python -m app.reembed` 로 다시 만든다).
--   - 활성 모델은 이후 백엔드가 시작할 때 EMBEDDER 설정에 맞춰 바꾼다 (app.services.embedding.activate_model).
--   - 카드 쪽 벡터 검색에도 활성 모델 조건을 넣는다 (match_cards).
-- =============================================================================
SET search_path = ax, public;

INSERT INTO ax.embedding_model (name, version, dimension, distance, is_active, note)
VALUES ('relay-ax/hash-ngram', '1', 1024, 'cosine', false,
        '개발·테스트용 결정적 해시 임베더 (문자 2·3-gram). 의미 이해 없음, 추천 품질 평가에 사용 금지')
ON CONFLICT (name, version) DO NOTHING;

DO $$
DECLARE
    v_hash smallint := (SELECT id FROM ax.embedding_model WHERE name = 'relay-ax/hash-ngram' AND version = '1');
    v_bge  smallint := (SELECT id FROM ax.embedding_model WHERE name = 'BAAI/bge-m3' AND version = '1');
    t text;
BEGIN
    IF v_bge IS NOT NULL THEN
        FOREACH t IN ARRAY ARRAY['chunk_embedding','card_embedding','demand_embedding',
                                 'company_tech_embedding','program_embedding','match_run'] LOOP
            EXECUTE format('UPDATE ax.%I SET model_id = $1 WHERE model_id = $2', t) USING v_hash, v_bge;
        END LOOP;
    END IF;
    -- 기본 임베더(hash)에 맞춘다. 한 번에 하나만 활성 (embedding_model_one_active)
    UPDATE ax.embedding_model SET is_active = false WHERE is_active AND id <> v_hash;
    UPDATE ax.embedding_model SET is_active = true WHERE id = v_hash;
END $$;

-- 카드 쪽 후보 검색에 활성 모델 조건 추가 (0015 정의에서 card_embedding 은 모델 구분이 없었다)
CREATE OR REPLACE FUNCTION ax.match_cards(
    p_demand_id    bigint,
    p_demand_facet text,
    p_card_facet   text,
    p_k            integer DEFAULT 20,
    p_published_only boolean DEFAULT true,
    p_oversample   integer DEFAULT 4
) RETURNS TABLE (card_id bigint, similarity double precision, matched_source_table text, matched_source_id bigint)
LANGUAGE plpgsql STABLE AS $$
BEGIN
    RETURN QUERY EXECUTE format($q$
        WITH m AS (
            SELECT id FROM ax.embedding_model WHERE is_active
        ), q AS (
            SELECT de.embedding
            FROM ax.demand_embedding de, m
            WHERE de.demand_id = %1$s AND de.facet = %2$L AND de.model_id = m.id
        ), hits AS (
            SELECT h.card_id, h.source_table, h.source_id, 1 - h.dist AS sim
            FROM q
            CROSS JOIN LATERAL (
                SELECT ce.card_id, ce.source_table, ce.source_id, ce.embedding <=> q.embedding AS dist
                FROM ax.card_embedding ce
                WHERE ce.facet = %3$L AND ce.model_id = (SELECT id FROM m)
                ORDER BY ce.embedding <=> q.embedding
                LIMIT %4$s
            ) h
        ), best AS (
            SELECT DISTINCT ON (hits.card_id) hits.card_id, hits.sim, hits.source_table, hits.source_id
            FROM hits
            ORDER BY hits.card_id, hits.sim DESC
        )
        SELECT b.card_id, b.sim, b.source_table, b.source_id
        FROM best b
        JOIN ax.achievement_card ac ON ac.id = b.card_id
        WHERE (NOT %5$L::boolean OR ac.status = 'PUBLISHED')
        ORDER BY b.sim DESC
        LIMIT %6$s
    $q$, p_demand_id, p_demand_facet, p_card_facet, p_k * p_oversample, p_published_only, p_k);
END $$;
