from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수(또는 .env)로 주입하는 설정. 접두어 없이 대문자 이름을 쓴다."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://localhost:5432/navigator"
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

    # 공고문 업로드 (POST /announcements/upload)
    upload_max_mb: int = 30           # 파일 크기 상한
    pdf_max_pages: int = 1000         # PDF 쪽 수 상한
    chunk_max_chars: int = 1000       # 청크 최대 글자 수 (청크는 쪽 경계를 넘지 않음)

    # 공고 지원 조건 뽑기: "auto"(기본) = LLM 자격증명이 있으면 LLM, 없으면 규칙 / "llm" / "rules"
    # 공개 공고문 글자만 보낸다 (기업 정보는 보내지 않음)
    requirement_extractor: str = "auto"
    llm_provider: str = "anthropic"   # anthropic | openai
    llm_model: str = ""               # 비우면 제공자 기본값 (DEFAULT_LLM_MODELS)
    llm_effort: str = "medium"        # low | medium | high | xhigh | max (비우면 보내지 않음)
    llm_max_tokens: int = 4000        # 사고(thinking) 토큰 포함 상한
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 2
    llm_server_fallback: bool = True  # 거절 시 서버측 대체 모델 (Claude API 전용, Bedrock 등에서는 false)
    anthropic_api_key: str | None = None  # 비우면 SDK 가 ANTHROPIC_API_KEY 환경변수 등에서 찾음
    openai_api_key: str | None = None     # 비우면 SDK 가 OPENAI_API_KEY 환경변수에서 찾음

    # 기업·공고
    navigator_public_base_url: str = "http://localhost:5173"  # 관리 링크 base URL
    navigator_link_ttl_days: int = 30
    navigator_rate_limit_per_minute: int = 60  # 공개 API, IP당
    navigator_dev_expose_link: bool = False    # 응답에 관리 링크 포함 (로컬 전용)
    navigator_match_candidate_k: int = 50
    hnsw_ef_search: int = 100
    navigator_ranking: str = "vector"   # vector = 판정 후 벡터 유사도 순 (A안) / weighted = 이전 가중합
    navigator_past_years: int = 2          # 참여할 수 있었던 사업: 마감 후 몇 년까지 볼지
    # 관련도 높음·보통 경계 (총점). 임베더마다 점수 폭이 달라 따로 둔다. 비우면 아래 기본값
    navigator_fit_high: float | None = None
    navigator_fit_mid: float | None = None
    mailer: str = "mock"                   # mock = 보내지 않고 OUTBOX 에만 / smtp = 실제 발송
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""                    # 비우면 smtp_user
    smtp_from_name: str = "Navigator"
    smtp_security: str = "starttls"        # starttls (587) | ssl (465) | none
    smtp_timeout_s: float = 15

    # 외부 수집. SOURCE_<CODE>=mock|live, 키는 live 에서만 필요
    collect_auto_minutes: int = 60          # 서버가 몇 분마다 주기가 된 출처를 수집할지. 0 이면 자동 수집 끔
    source_nts_biz: str = "mock"
    source_kipris: str = "mock"
    source_dart: str = "mock"
    source_bizinfo: str = "mock"
    source_krit: str = "mock"
    nts_service_key: str | None = None      # 공공데이터포털 (국세청 사업자등록정보)
    kipris_access_key: str | None = None    # KIPRIS Plus
    dart_api_key: str | None = None         # OpenDART
    bizinfo_api_key: str | None = None      # 기업마당
    krit_max_pages: int = 3                 # 국기원 공지사항 한 번에 읽을 쪽 수 (쪽당 10건). 처음 채울 때는 61
    krit_request_delay_s: float = 0.5       # 국기원 요청 사이 대기 (동시·연속 요청 시 빈 페이지가 옴)
    navigator_announcement_keywords: str = "국방,방산,방위산업,방위사업,무기체계,군수"   # 외부 공고 거르기 (쉼표)

    @property
    def resolved_llm_model(self) -> str:
        return self.llm_model or DEFAULT_LLM_MODELS.get(self.llm_provider.lower(), "")


DEFAULT_LLM_MODELS = {"anthropic": "claude-opus-5-5", "openai": "gpt-5.5"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
