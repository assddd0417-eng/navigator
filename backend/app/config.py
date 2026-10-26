from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수(또는 .env)로 주입하는 설정. 접두어 없이 대문자 이름을 쓴다."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://localhost:5432/relay_ax"
    db_pool_min: int = 1
    db_pool_max: int = 10

    # 임베딩: "hash" = 결정적 해시 임베더(개발·테스트용), "bge_m3" = sentence-transformers BGE-M3
    embedder: str = "hash"
    embedding_model_path: str = "BAAI/bge-m3"
    embedding_dim: int = 1024  # 스키마 vector(1024) 와 일치해야 함

    # 매칭
    match_top_k: int = 20             # 최종 추천 수
    match_facet_k: int = 30           # 패싯별 후보 수
    match_min_score: float = 0.35     # 미만이면 is_excluded 로 보존
    hnsw_ef_search: int = 100
    rag_evidence_k: int = 3           # 추천당 RAG 근거 청크 수


@lru_cache
def get_settings() -> Settings:
    return Settings()
