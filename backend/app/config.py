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
    embedding_model_name: str = "BAAI/bge-m3"   # ax.embedding_model.name (벡터를 모델별로 구분하는 이름)
    embedding_model_path: str = "BAAI/bge-m3"   # 로드 경로: Hugging Face 이름 또는 반입한 로컬 폴더
    embedding_dim: int = 1024                   # 스키마 vector(1024) 와 일치해야 함
    embedding_device: str = "auto"              # auto(cuda → mps → cpu) | cpu | mps | cuda
    embedding_max_seq_length: int = 1024        # 토큰. 청크 길이에 맞춰 줄이면 메모리·속도 이득 (모델 최대 8192)
    embedding_batch_size: int = 16
    embedding_offline: bool = False             # true = 네트워크 없이 캐시·로컬 폴더에서만 로드 (폐쇄망)
    embedding_cache_dir: str | None = None      # 모델 캐시 위치 (기본: ~/.cache/huggingface)

    # 문서 업로드 (POST /documents/upload, /documents/parse)
    upload_max_mb: int = 30           # 파일 크기 상한
    pdf_max_pages: int = 1000         # PDF 쪽 수 상한
    chunk_max_chars: int = 1000       # 청크 최대 글자 수 (청크는 쪽 경계를 넘지 않음)

    # 매칭
    match_top_k: int = 20             # 최종 추천 수
    match_facet_k: int = 30           # 패싯별 후보 수
    match_min_score: float = 0.35     # 미만이면 is_excluded 로 보존
    hnsw_ef_search: int = 100
    rag_evidence_k: int = 3           # 추천당 RAG 근거 청크 수

    # 연계이유 문장: "template"(기본) = 규칙 템플릿만, 외부 전송 없음
    #   "auto" = API 키가 있으면 LLM, 없으면 템플릿 / "llm" = 항상 LLM 시도
    # LLM(anthropic·openai)은 외부 API 로 수요·카드 정보와 근거 인용문을 보내므로 명시적으로 켤 때만 쓴다.
    # LLM 실패·근거 검증 탈락 시에는 추천별로 템플릿 문장을 쓴다
    rationale_generator: str = "template"
    llm_provider: str = "anthropic"   # anthropic | openai
    llm_model: str = ""               # 비우면 제공자 기본값 (DEFAULT_LLM_MODELS)
    llm_effort: str = "medium"        # low | medium | high | xhigh | max (비우면 보내지 않음)
    llm_max_tokens: int = 4000        # 사고(thinking) 토큰 포함 상한
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 2
    llm_concurrency: int = 4          # 한 매칭 실행에서 동시에 보낼 요청 수
    llm_server_fallback: bool = True  # 거절 시 서버측 대체 모델 (Claude API 전용, Bedrock 등에서는 false)
    llm_evidence_max_security: str = "INTERNAL"  # 이 등급을 넘는 문서의 원문은 외부 LLM 에 보내지 않음
    anthropic_api_key: str | None = None  # 비우면 SDK 가 ANTHROPIC_API_KEY 환경변수 등에서 찾음
    openai_api_key: str | None = None     # 비우면 SDK 가 OPENAI_API_KEY 환경변수에서 찾음

    # Navigator (기업 대상 서비스): 기업은 로그인 없이 사업자번호 + 관리 링크로 쓴다
    navigator_public_base_url: str = "http://localhost:5173"  # 관리 링크 주소의 앞부분 (기업 화면)
    navigator_link_ttl_days: int = 30          # 관리 링크 유효 기간
    navigator_rate_limit_per_minute: int = 60  # 로그인 없는 API: 같은 곳에서 1분에 이 횟수까지
    navigator_dev_expose_link: bool = False    # true = 응답에 관리 링크를 그대로 실어 줌 (로컬 확인용, 운영 금지)
    mailer: str = "mock"                       # mock = 보내지 않고 기록만 (실제 발송은 5단계)
    # 외부 출처 연결 부품: mock | live (출처 코드 = ax.external_source.code)
    source_nts_biz: str = "mock"

    @property
    def resolved_llm_model(self) -> str:
        return self.llm_model or DEFAULT_LLM_MODELS.get(self.llm_provider.lower(), "")


DEFAULT_LLM_MODELS = {"anthropic": "claude-opus-5-5", "openai": "gpt-5.5"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
