-- =============================================================================
-- (선택) IVFFlat 인덱스 대안
--   HNSW 대비 빌드가 빠르고 메모리 사용이 적으나 재현율이 낮고,
--   데이터 적재 "후" 생성해야 centroid 품질이 확보된다.
--   청크 수가 수백만 건 이상으로 커져 HNSW 빌드 시간/메모리가 부담될 때 고려.
--   lists 권장값: 행 수 100만 이하 → rows/1000, 초과 → sqrt(rows)
--   조회 시: SET ivfflat.probes = 10;  (lists 의 sqrt 수준부터 조정)
-- 적용 방법: 해당 HNSW 인덱스를 DROP 후 아래 실행 (마이그레이션과 별도 운영 작업)
-- =============================================================================
SET search_path = ax, public;

-- DROP INDEX IF EXISTS ax.chunk_embedding_hnsw;
CREATE INDEX IF NOT EXISTS chunk_embedding_ivfflat ON ax.chunk_embedding
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 1000);
