-- =============================================================================
-- 0001: 확장 모듈, 스키마, 공통 유틸리티
--   - pgvector  : 임베딩 저장 및 HNSW/IVFFlat 근사 최근접 탐색
--   - pg_trgm   : 한국어 키워드 부분일치 검색(형태소 분석기 미사용 환경 대안)
--   - 공통 트리거 함수 : updated_at 자동 갱신, 현재 사용자(app.current_user_id) 조회
-- 실행 전제: PostgreSQL 16, pgvector >= 0.5.0 (HNSW 지원)
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE SCHEMA IF NOT EXISTS ax;
COMMENT ON SCHEMA ax IS '국방 R&D 성과연계·이어달리기 AX PoC 스키마';

SET search_path = ax, public;

-- 마이그레이션 이력 (프레임워크 미정이므로 scripts/migrate.sh 가 사용)
CREATE TABLE IF NOT EXISTS ax.schema_migrations (
    version     text PRIMARY KEY,               -- 예: '0001'
    filename    text        NOT NULL,
    checksum    text        NOT NULL,           -- 파일 sha256
    applied_at  timestamptz NOT NULL DEFAULT now()
);

-- updated_at 자동 갱신
CREATE OR REPLACE FUNCTION ax.set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END $$;

-- 백엔드가 트랜잭션마다 `SET LOCAL app.current_user_id = '<user id>'` 로 설정한다.
-- 감사 로그·검토 이력의 행위자 식별에 사용. 미설정 시 NULL (배치/시스템 작업).
CREATE OR REPLACE FUNCTION ax.current_app_user() RETURNS bigint
LANGUAGE sql STABLE AS $$
    SELECT NULLIF(current_setting('app.current_user_id', true), '')::bigint
$$;

-- 백엔드가 요청 추적용으로 `SET LOCAL app.request_id = '<uuid>'` 설정 (선택)
CREATE OR REPLACE FUNCTION ax.current_request_id() RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT NULLIF(current_setting('app.request_id', true), '')
$$;
