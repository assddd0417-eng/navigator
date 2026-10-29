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

    # 연계이유 문장: "template" = 규칙 템플릿(기본), "llm" = LLM 생성(실패·키 없음 시 템플릿으로 대체)
    rationale_generator: str = "template"
    llm_provider: str = "anthropic"
    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "medium"        # low | medium | high | xhigh | max
    llm_max_tokens: int = 4000        # 사고(thinking) 토큰 포함 상한
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 2
    llm_concurrency: int = 4          # 한 매칭 실행에서 동시에 보낼 요청 수
    llm_server_fallback: bool = True  # 거절 시 서버측 대체 모델 (Claude API 전용, Bedrock 등에서는 false)
    llm_evidence_max_security: str = "INTERNAL"  # 이 등급을 넘는 문서의 원문은 외부 LLM 에 보내지 않음
    anthropic_api_key: str | None = None  # 비우면 SDK 가 ANTHROPIC_API_KEY 환경변수 등에서 찾음


@lru_cache
def get_settings() -> Settings:
    return Settings()
