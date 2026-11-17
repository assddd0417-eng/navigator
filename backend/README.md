# 백엔드 (FastAPI)

`../db/migrations` 스키마 위에서 동작하는 Navigator API. ORM 없이 psycopg 3 + SQL 로 작성했다. API 목록·판정 규칙은 [docs/navigator.md](../docs/navigator.md).

## 실행

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"            # BGE-M3 를 쓰려면 ".[dev,bge]"
cp .env.example .env               # DATABASE_URL 수정
DATABASE_URL=... ../scripts/migrate.sh
uvicorn app.main:app --reload      # http://localhost:8000/docs
```

## BGE-M3 로 실행 (Apple Silicon Mac 기준)

```bash
cd backend && source .venv/bin/activate
pip install -e ".[dev,bge]"           # sentence-transformers + torch (macOS arm64 휠은 MPS 포함)
export EMBEDDER=bge_m3                # 또는 .env 에 기록
uvicorn app.main:app --port 8000      # 첫 실행: Hugging Face 에서 BAAI/bge-m3(약 2.3GB) 내려받아 캐시
python -m app.reembed                 # 다른 터미널에서. 기존 공고문·기업·공고를 BGE-M3 로 다시 임베딩
curl -s localhost:8000/health         # embedding.model = BAAI/bge-m3, reindex_needed = false 확인
```

- 장치: `EMBEDDING_DEVICE=auto` 는 CUDA → MPS → CPU 순으로 고른다. MPS 에서 문제가 있으면 `EMBEDDING_DEVICE=cpu`.
- 메모리: `EMBEDDING_MAX_SEQ_LENGTH`(기본 1024 토큰)와 `EMBEDDING_BATCH_SIZE`(기본 16)를 줄이면 M2 8GB 에서도 여유가 생긴다.
- 서버는 시작할 때 모델을 먼저 올리고(첫 요청 지연 방지), 추론은 스레드에서 돌려 다른 요청을 막지 않는다.
- 폐쇄망: 모델 폴더를 반입하고 `EMBEDDING_MODEL_PATH=/opt/models/bge-m3`, `EMBEDDING_OFFLINE=true` (네트워크 접근 없음). 캐시 위치는 `EMBEDDING_CACHE_DIR`.
- 되돌리기: `EMBEDDER=hash` 로 서버를 띄우고 `python -m app.reembed`. 이전 모델 벡터를 지우지 않으려면 `--keep-other-models`.

**벡터 분리 원칙**: 임베더마다 `ax.embedding_model` 행이 따로 있고(`navigator/hash-ngram`, `BAAI/bge-m3`),
서버가 시작할 때 `EMBEDDER` 에 맞는 행을 활성으로 만든다. 매칭은 활성 모델 벡터만 보므로 hash 벡터와 BGE-M3 벡터가 섞이지 않는다.
재임베딩 전에는 기존 데이터가 매칭에 나오지 않으며, 서버 로그와 `/health` 의 `reindex_needed` 가 알려 준다.
같은 DB 에 서로 다른 `EMBEDDER` 로 서버 두 개를 띄우지 않는다 (활성 모델을 서로 바꾼다).

## 테스트

빈 테스트 DB(`navigator_test`)를 만들고, 마이그레이션과 기본 데이터를 넣은 뒤 실제 PostgreSQL 에 대해 API 흐름을 검증한다.

```bash
TEST_ADMIN_DATABASE_URL=postgresql://postgres@localhost:5432/postgres pytest
```

## 구조

```
app/
  main.py            앱, 요청 ID 미들웨어, /health, /me
  site.py            API(/api) + 빌드된 화면을 한 주소로
  config.py          환경변수 설정
  db.py              연결 풀, 요청 단위 트랜잭션 (app.current_user_id·request_id SET LOCAL)
  auth.py            PoC 인증 (X-User-Id 헤더) + 역할 검사 → 운영 시 SSO/JWT 로 교체
  errors.py          DB 오류 → HTTP (check_violation 422, insufficient_privilege 403, unique 409)
  routers/           navigator(기업), announcements(공고), navigator_matching, navigator_alerts, navigator_sources
  services/
    embedding.py           Embedder(Hash/BGE-M3), 모델 활성화, 임베딩 동기화(sha256 변경 감지)
    navigator_embedding.py 기업·공고 facet 텍스트
    navigator_matching.py  기업↔공고 매칭, 판정·점수·근거 저장
    eligibility.py         자격요건 판정 (순수 함수)
    requirement_extract.py 공고문에서 지원 조건 뽑기 (규칙 / LLM)
    announcement_docs.py   공고문 파일 읽기·청크 저장
    navigator_alerts.py    공고 알림, navigator_outreach.py 참여 권유, mailer.py 메일
    collector.py, external/ 외부 수집 (국세청·KIPRIS·DART·기업마당·국기원)
    llm.py                 LLM 제공자 클라이언트 (Anthropic, OpenAI)
  reembed.py         전체 재임베딩 CLI (python -m app.reembed)
  collect.py         외부 수집 CLI (python -m app.collect)
  navigator_eval.py  판정·추천 검증 (python -m app.navigator_eval)
```

## 공고 조건 뽑기 LLM (선택)

`REQUIREMENT_EXTRACTOR=auto`(기본)면 키가 있을 때 LLM, 없으면 규칙으로 뽑는다. LLM 에는 공개 공고문 글자만 보낸다.

```bash
pip install -e ".[llm]"
export ANTHROPIC_API_KEY=sk-ant-...      # 또는 LLM_PROVIDER=openai, OPENAI_API_KEY=...
```
