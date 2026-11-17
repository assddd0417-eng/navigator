# 백엔드 (FastAPI)

`../db/migrations` 스키마 위에서 동작하는 PoC API. ORM 없이 psycopg 3 + SQL 로 작성했고, 업무 규칙 중 무결성에 해당하는 것(검토 진입 가드, 최종판정 권한, 추가 전용 이력)은 DB 트리거가 강제한다. API 는 그 오류를 HTTP 상태로 바꿔 돌려준다.

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
python -m app.reembed                 # 다른 터미널에서. 기존 문서·카드·수요를 BGE-M3 로 다시 임베딩
curl -s localhost:8000/health         # embedding.model = BAAI/bge-m3, reindex_needed = false 확인
```

- 장치: `EMBEDDING_DEVICE=auto` 는 CUDA → MPS → CPU 순으로 고른다. MPS 에서 문제가 있으면 `EMBEDDING_DEVICE=cpu`.
- 메모리: `EMBEDDING_MAX_SEQ_LENGTH`(기본 1024 토큰)와 `EMBEDDING_BATCH_SIZE`(기본 16)를 줄이면 M2 8GB 에서도 여유가 생긴다.
- 서버는 시작할 때 모델을 먼저 올리고(첫 요청 지연 방지), 추론은 스레드에서 돌려 다른 요청을 막지 않는다.
- 폐쇄망: 모델 폴더를 반입하고 `EMBEDDING_MODEL_PATH=/opt/models/bge-m3`, `EMBEDDING_OFFLINE=true` (네트워크 접근 없음). 캐시 위치는 `EMBEDDING_CACHE_DIR`.
- 되돌리기: `EMBEDDER=hash` 로 서버를 띄우고 `python -m app.reembed`. 이전 모델 벡터를 지우지 않으려면 `--keep-other-models`.

**벡터 분리 원칙** (마이그레이션 0016): 임베더마다 `ax.embedding_model` 행이 따로 있고(`relay-ax/hash-ngram`, `BAAI/bge-m3`),
서버가 시작할 때 `EMBEDDER` 에 맞는 행을 활성으로 만든다. 검색·매칭은 활성 모델 벡터만 보므로 hash 벡터와 BGE-M3 벡터가 섞이지 않는다.
재임베딩 전에는 기존 데이터가 검색·매칭에 나오지 않으며, 서버 로그와 `/health` 의 `reindex_needed` 가 알려 준다.
같은 DB 에 서로 다른 `EMBEDDER` 로 서버 두 개를 띄우지 않는다 (활성 모델을 서로 바꾼다).

## 테스트

빈 테스트 DB(`relay_ax_test`)를 만들고, 마이그레이션과 기본 데이터를 넣은 뒤 실제 PostgreSQL 에 대해 API 전체 흐름을 검증한다.

```bash
TEST_ADMIN_DATABASE_URL=postgresql://postgres@localhost:5432/postgres pytest
```

## 구조

```
app/
  main.py            앱, 요청 ID 미들웨어, /health
  config.py          환경변수 설정
  db.py              연결 풀, 요청 단위 트랜잭션 (app.current_user_id·request_id SET LOCAL)
  auth.py            PoC 인증 (X-User-Id 헤더) + 역할 검사 → 운영 시 SSO/JWT 로 교체
  errors.py          DB 오류 → HTTP (check_violation 422, insufficient_privilege 403, unique 409)
  routers/           documents, cards, demands, recommendations(검토), kpi
  services/
    embedding.py     Embedder(Hash/BGE-M3), 모델 활성화, 카드·수요 패싯 텍스트, 임베딩 동기화(sha256 변경 감지)
  reembed.py         전체 재임베딩 CLI (python -m app.reembed)
    scoring.py       5개 기준 점수, 6대 연계유형 분류, 융합형 판정 (순수 함수)
    matching.py      수요→성과 매칭 실행, 추천·점수·근거·부서/기업 후보 저장
    rationale.py     연계이유·개발필요사항 문장 (템플릿 + LLM 연계이유 생성·근거 검증)
    llm.py           LLM 제공자 클라이언트 (Anthropic Claude, 교체 가능)
```

## 주요 API

| 메서드 | 경로 | 역할 | 설명 |
|---|---|---|---|
| POST | `/documents` | CURATOR, PLANNER | 파싱·청킹된 문서 등록 + 청크 임베딩 |
| POST | `/documents/upload` | CURATOR, PLANNER | **파일 업로드**(PDF·TXT·MD, multipart) → 텍스트 추출·쪽 단위 청킹·등록·임베딩 |
| POST | `/documents/parse` | CURATOR, PLANNER | 같은 추출·청킹 결과를 저장 없이 미리보기 |
| GET | `/documents` | 모두 | 문서 처리 현황 (열람 가능한 문서만, 처리상태·청크 수) |
| GET | `/me` | 모두 | 현재 사용자·역할 (프론트엔드 화면 분기용) |
| POST | `/documents/search` | 모두 | 권한 필터 RAG 검색 |
| POST/GET | `/cards`, `/cards/{id}` | CURATOR, PLANNER / 모두 | 성과 활용카드 (하위 항목·관계·원문 근거 포함) |
| PATCH | `/cards/{id}` | CURATOR, PLANNER | 수정 (revision +1, 재임베딩) |
| POST | `/cards/{id}/publish` | CURATOR | 검수 확정 → 매칭 대상 |
| POST/GET | `/demands`, `/demands/{id}` | PLANNER / 모두 | 신규 기획수요 (요구성능·기술요소·무기체계) |
| POST | `/demands/{id}/match` | PLANNER | 매칭 실행 → match_run id |
| GET | `/match-runs/{id}` | 모두 | 실행 결과와 추천 목록 |
| GET | `/recommendations/{id}` | 모두 | 점수·유형확률·근거(열람 가능 문서만)·부서/기업/품목 후보·검토 |
| POST | `/recommendations/{id}/assignments` | PLANNER | 검토 배정 (근거 없음·융합형 카드 부족 시 422) |
| POST | `/recommendations/{id}/decisions` | DEPT_REVIEWER, EXPERT | 의견·판정. 최종판정은 DEPT_REVIEWER 만 (403) |
| POST | `/recommendations/{id}/withdraw` | PLANNER | 철회 (사유 기록) |
| GET | `/recommendations/{id}/history` | 모두 | 상태 이력 + 감사 로그 |
| POST | `/recommendations/{id}/confirmations`, PATCH `/confirmations/{id}` | 모두 | 추가 확인 필요사항 |
| GET | `/reviews/queue` | 모두 | 본인·본인 부서 검토 대기열 |
| GET | `/kpi/recommendations`, `/kpi/eval`, `/kpi/work-time` | 모두 | PoC 정량목표 |
| POST | `/overseas/import` | PLANNER, CURATOR | **해외 수요 정리 엑셀** 올리기 (`dry_run=true` 면 검사만) |
| POST/GET | `/overseas/sources`, `/overseas/demands`, `/overseas/demands/{id}` | PLANNER, CURATOR / 모두 | 해외 수요 출처·수요 (같은 번호면 갱신) |
| GET | `/overseas/demands/{id}/similar-cards` | 모두 | 해외 수요와 가까운 국내 성과 카드 (갭 분석 1단계) |
| POST | `/gaps/runs` | PLANNER, CURATOR | 갭 분석 지금 실행 (`demand_ids` 비우면 전체, `rules` 로 기준값 시험) |
| GET | `/gaps/runs`, `/gaps/runs/{id}` | 모두 | 실행 기록 (자동·수동)과 그 실행의 갭 |
| GET | `/gaps/findings`, `/gaps/findings/{id}` | 모두 (보안등급별) | 갭 목록(점수 순)·근거 카드·제안 경로·해외 출처 |
| POST | `/gaps/findings/{id}/decision` | DEPT_REVIEWER | 갭 확정·기각 (기각은 사유 필수) |
| GET | `/gaps/summary` | 모두 | 해외 수요별 열린 갭 종류 한눈에 보기 |
| GET | `/portfolio/overview`·`/areas`·`/domestic`·`/actions` | PLANNER, DEPT_REVIEWER, VIEWER (보안등급별) | 기관 포트폴리오: 숫자·분야별 대조표·무기체계별 국내 성과·정책 기획 후보 (`include_draft`, `area`) |
| GET | `/portfolio/export.xlsx` | PLANNER, DEPT_REVIEWER, VIEWER | 위 내용을 엑셀로 (분야별 대조·국내 성과 분포·기획 후보·작성기준) |
| POST | `/portfolio/actions/{갭id}/to-demand` | PLANNER | 확정된 갭 → 신규 기획수요(OPEN). 이미 넘긴 갭이면 200 + 기존 기획수요 (0028) |
| POST | `/review-sheets` | PLANNER | 이어달리기 후보 검토표 만들기 (범위: 전체·종료과제 활용·사업트랙/부서 간·기획수요, 부서·회의 선택). 열람 가능한 최근 추천을 사본으로 저장 (0036) |
| GET | `/review-sheets`·`/review-sheets/{id}` | PLANNER, DEPT_REVIEWER (보안등급별) | 검토표 목록·상세 (항목 사본 + 지금 검토 상태 + 담당부서 최종 검토율·원문 근거 연결) |
| PATCH·DELETE | `/review-sheets/{id}`·`/review-sheets/{id}/items/{추천id}` | PLANNER | 회의에 올리기·제목, 확정 전 후보 빼기 |
| POST | `/review-sheets/{id}/finalize` | PLANNER | 검토표 확정 (이후 항목 변경 불가, DB 가 막음) |
| GET | `/review-sheets/{id}/export.xlsx` | PLANNER, DEPT_REVIEWER | 회의자료 엑셀 (검토표·회의 결정·작성기준) |
| POST | `/review-sheets/{id}/drafts` | PLANNER | 통합기획 자료 초안 (Markdown, 원문 근거 각주, 다시 만들면 판 올림) |
| GET·PATCH | `/planning-drafts/{id}`·`/planning-drafts/{id}/export.md` | 보기 PLANNER·DEPT_REVIEWER, 상태 PLANNER | 초안 보기·내려받기·검토함/최종 표시 |
| POST·GET·PATCH | `/meetings`·`/meetings/{id}` | 만들기 PLANNER, 보기 PLANNER·DEPT_REVIEWER | 통합기획 회의 (참석 부서, 올린 검토표, 결정) |
| POST | `/meetings/{id}/decisions` | PLANNER | 회의 결정·후속조치 (추천에 대한 결정은 회의에 올린 검토표의 후보만) |
| PATCH | `/meeting-decisions/{id}` | PLANNER 또는 담당 부서 DEPT_REVIEWER | 후속조치 상태 (진행·완료·취소) |
| GET | `/executions/candidates` | PLANNER, DEPT_REVIEWER | 담당부서가 채택한 추천 (실행 기록 수 포함) |
| POST | `/executions` | PLANNER 또는 그 추천의 담당부서 DEPT_REVIEWER | 연계 실행 기록 (채택 추천만, 이어진 과제 지정·새 과제번호 등록 → 실제 이어달리기 과제 관계 자동) (0037) |
| PATCH | `/executions/{id}` | 같음 | 상태·결과 갱신. 완료(COMPLETED)면 실제 연계 사례 검증 케이스(eval_case HISTORICAL_RELAY) 자동 생성 |
| GET | `/executions`·`/executions/kpi` | PLANNER, DEPT_REVIEWER (보안등급별) | 실행 목록, 순환 지표(채택→실행 전환율·AX 발굴·이어진 과제·새 성과·검증 사례) |
| GET | `/executions/lineage/cards/{카드id}` | PLANNER, DEPT_REVIEWER | 이어달리기 계보: 앞 과제(실제 이어달리기 관계) ↔ 이 성과 → 실행 → 이어진 과제 → 새 성과 |
| POST·GET·DELETE | `/measurements/work-time` | 입력 PLANNER·DEPT_REVIEWER·EXPERT·CURATOR (본인 것만 삭제), 전체 보기 PLANNER·DEPT_REVIEWER (`mine=false`) | 업무시간 측정: 같은 업무를 수작업·AX 로 한 시간(분)·찾은 후보 수 |
| POST | `/measurements/surveys` | 같음 | 만족도 1~5 (쓸모·근거·쓰기 쉬움·시간 단축 항목별 선택) |
| GET | `/measurements/summary`·`/measurements/export.xlsx` | PLANNER, DEPT_REVIEWER | 업무별 평균·단축률·제안서 목표(조사 70%, 검토자료 60%) 달성, 후보 수, 역할별 만족도, 엑셀 |
| GET | `/synonyms`·`/synonyms/expand?text=` | 모두 | 국방기술 용어 사전 보기, 이 글이 사전으로 어떻게 넓혀지는지 미리 보기 |
| POST·PATCH·DELETE | `/synonyms`·`/synonyms/{id}` | PLANNER, CURATOR | 용어 넣기·끄기·지우기 (관계: 동의어·약어·영문·한글은 매칭에 씀, 넓은 말·좁은 말·관련어는 참고만) |
| POST | `/synonyms/import` | PLANNER, CURATOR | 엑셀 올리기 (머리글 `표준 용어·동의어·관계·분야·출처`, `dry_run=true` 면 검사만) |
| POST | `/synonyms/apply` | PLANNER, CURATOR | 사전을 성과카드·기획수요·해외 수요 임베딩에 반영 (글이 바뀐 패싯만 다시 계산). 문서 검색 질의는 바로 반영 |
| POST | `/planning/trends` | PLANNER, CURATOR | 동향 직접 입력 (해외 3종 + 국내 계획·성능개량·국산화/단종 대응). 출처 메모 필수, 저장 즉시 갭 분석 |
| GET | `/planning/trends` | PLANNER, DEPT_REVIEWER, CURATOR | 동향 목록 (해외 수요 + 직접 입력), 만든 기획수요 번호 |
| GET | `/planning/brief/{동향id}` | PLANNER, DEPT_REVIEWER, CURATOR | 기획 참고서: 관련 과거 과제(결과 구분·한계·평가 의견)·요구 성능 비교·새 기획에 넣을 것 (`k`, `min_sim`) |
| POST | `/planning/brief/{동향id}/to-demand` | PLANNER | 참고서로 신규 기획수요(OPEN) + 참고서 사본(planning_draft). 이미 있으면 200 + 기존 것 |
| GET | `/planning/demands/{기획수요id}/brief` | PLANNER, DEPT_REVIEWER, CURATOR | 기획수요에 붙은 참고서 사본 (Markdown) |
| GET·POST | `/planning/projects/{과제id}/evaluations` | 읽기 위 3역할 · 쓰기 PLANNER, CURATOR | 과제 평가 의견 (결과평가·중간평가·전문가·소요군). 과제보다 낮은 보안등급 불가 (0029) |
| GET | `/planning/projects/{과제id}/chain` | PLANNER, DEPT_REVIEWER, CURATOR | 자료 사슬 (사업 기획서 → 공모서 → 연구개발계획서 → 결과보고서 → 평가서)과 과제의 다른 번호 (0032) |
| POST | `/planning/projects/{과제id}/identifiers` | PLANNER, CURATOR | 과제의 다른 번호 등록 (PMS·DTiMS 번호가 다를 때). 같은 시스템 같은 번호는 한 과제만 |
| POST | `/planning/documents/{문서id}/relink` | PLANNER, CURATOR | 문서를 과제번호·다른 번호·과제명으로 다시 연결 |
| PUT | `/planning/projects/{과제id}/outcome` | PLANNER, CURATOR | 과제 결과 구분 (전력화·후속·기술만·전환 실패·중단). 실패·중단은 원인 필수 (DB 강제) |

## 문서 파일 업로드 (PDF)

`app/services/document_parser.py`. `POST /documents/upload` 에 `file` 과 폼 필드(`doc_type_code` 필수, `title`·`project_id`·`owner_dept_id`·`security_code` 등)를 보낸다.

```bash
curl -X POST localhost:8000/documents/upload -H 'X-User-Id: 4' \
  -F file=@결과보고서.pdf -F doc_type_code=FINAL_REPORT -F project_id=1 -F owner_dept_id=3
```

- **파서 = pdfplumber** (pdfminer.six 기반). pypdf 는 한국어 PDF 에서 어절 사이 공백을 자주 잃어 ("정보가부서·사업트랙별로분산") 임베딩·검색 품질이 떨어진다. 실제 과제 제안서 PDF 로 비교해 결정. 순수 Python + 휠이라 폐쇄망 반입이 쉽다.
- 청크는 **쪽 경계를 넘지 않는다** → 모든 청크에 출처 쪽(`page_start=page_end`, `location.page`)이 붙는다. 쪽 안에서는 시각적 줄바꿈을 이어 붙이고 글머리표(•, ㅇ, -, 1.2. …)·문장 끝에서 문단을 나눈 뒤 `CHUNK_MAX_CHARS`(기본 1000자) 이내로 채운다. 머리·꼬리 쪽 번호 줄은 버린다.
- 텍스트 파일은 UTF-8, 안 되면 CP949 로 읽고 빈 줄 기준 문단으로 나눈다.
- 원본 파일은 저장하지 않는다 (`storage_uri` 없음). 파일명·SHA-256·파서·텍스트 없는 쪽은 `source_document.metadata` 에 남는다.
- 오류 (`detail` + `kind`):

| 상황 | HTTP | kind |
|---|---|---|
| 스캔본 등 모든 쪽에 텍스트 없음 (OCR 미지원) | 422 | `no_text_layer` |
| 일부 쪽만 텍스트 없음 | 201, `warnings`·`pages_without_text` 로 안내 | – |
| 열람 암호가 걸린 PDF | 422 | `encrypted_pdf` |
| 손상·잘린 PDF, PDF 시그니처 없는 .pdf | 422 | `corrupt_pdf` |
| 빈 파일 / 텍스트 인코딩 불명 | 422 | `empty_file` / `invalid_encoding` |
| HWP 등 지원하지 않는 형식 | 415 | `unsupported_type` |
| `UPLOAD_MAX_MB`(30) 초과 / `PDF_MAX_PAGES`(1000) 초과 | 413 | `file_too_large` / `too_many_pages` |

범위 밖: OCR, 표 구조 추출(표 글자는 본문으로 들어감), 조항(목차) 자동 인식, 원본 파일 보관.

## 해외 수요 올리기

`app/routers/overseas.py`, 스키마 0023. 해외 기술 로드맵·공모·수출 요구를 공식 기관 자료에서 뽑아 엑셀로 정리한 뒤 올린다.
예시 파일: `seeds/overseas/전차파워팩_해외수요.xlsx` (출처 9건, 해외 수요 9건).

```bash
curl -X POST "localhost:8000/overseas/import?dry_run=true" -H 'X-User-Id: 1' -F file=@seeds/overseas/전차파워팩_해외수요.xlsx
curl -X POST "localhost:8000/overseas/import" -H 'X-User-Id: 1' -F file=@seeds/overseas/전차파워팩_해외수요.xlsx
```

- 시트 `출처`: 출처 번호 · 발행 기관 · 문서 제목 · 발행일 · URL · 자료 종류 · 이용 조건 · 원문 저장 허용 · 확인한 날 · 비고
- 시트 `해외수요`: 수요 번호 · 출처 번호(여러 개면 쉼표, 첫 번째가 주 출처) · 국가/기관 · 수요 제목 · 기술분류 · 무기체계/품목 · 요구 성능 · 목표 시기 · 수요 종류(기술로드맵/공모/수출요구) · 원문 인용 · 확신도(높음/보통/낮음) · 메모
- 한 행이라도 틀리면 아무것도 저장하지 않고 `detail.errors` 에 행별 이유를 돌려준다 (422).
- DB 규칙: 출처마다 URL·이용 조건·확인일 필수, 원문 저장 허용이 아니면 원문 문서 연결 불가, 해외 수요의 보안등급은 출처보다 낮을 수 없다.
- 해외 수요도 국내 성과 카드와 같은 모델로 임베딩한다 (`overseas_demand_embedding`). 임베더를 바꾸면 `python -m app.reembed` 가 함께 다시 만든다.

비교할 국내 성과 (K2전차 파워팩): `seeds/overseas/국내성과_K2파워팩.json`

| 카드 | 공식 근거 | 비교 대상 해외 수요 |
|---|---|---|
| SYN-AC-K2T 국산 자동변속기 | 방위사업청 제164회 방추위 결과(2024-10-28): 내구도 검사 320시간 중 306시간 후 결함, 4차 양산 적용 결정 | D08 기준 제원 |
| SYN-AC-K2E 국산 디젤엔진 | 같은 보도자료(파워팩 완전 국산화), 폴란드 국방부 K2 제원·하원 답변 2728(엔진 포함 부체계 수리 문서 이전) | D08, D06·D09 현지 생산·정비 |

수치와 사업 경과는 위 공식 자료 그대로이고, 결과보고서 문장과 기업명((가상))은 합성이다.

```bash
python -m app.synthetic load --corpus ../seeds/overseas/국내성과_K2파워팩.json   # 카드 2개 적재 (재실행 안전)
```

## 갭 분석

`app/services/gap_rules.py`(판정 규칙, DB 없음) · `app/services/gap_analysis.py`(실행·저장) · `app/routers/gaps.py`, 스키마 0026.
해외 수요마다 가까운 국내 성과 카드(검수 확정분, 최대 10건)를 모아 갭 종류 4가지를 판정한다.

| 갭 종류 | 판정 | 제안 경로 |
|---|---|---|
| 공백 `NO_COVERAGE` | 가장 가까운 카드의 유사도가 기준(0.55) 미만 | 신규 기획수요 (부분적으로 가까운 카드가 2건 이상이면 융합형도) |
| 성능미달 `PERFORMANCE_SHORT` | 비슷한 카드가 해외 요구 수치에 못 미치거나, 자기 목표를 달성하지 못함 (단위가 다르면 비교 안 함) | 고도화형 |
| 국산화·현지화 `LOCALIZATION` | 비슷한 카드 품목(BOM 하위 포함)에 수입품이 있음, 또는 수출 요구에 현지 생산·정비 낱말이 있음. 카드 전체가 기준 미만이어도 미해결 현지화 과제가 요구와 맞으면(유사도 0.45 이상) 공백 대신 이 종류 | 전환형 / 사업화형 |
| 성숙도부족 `MATURITY` | 비슷한 카드 중 최고 TRL 이 7 미만, 또는 이 수요와 관련된 미해결 과제가 남음 | 후속형 |

- 점수 = 갭 크기 × 수요 확신도(높음 1.0 · 보통 0.8 · 낮음 0.6) × 시급성(목표 시기 2년 안 1.0 · 5년 안 0.85 · 그 뒤 0.7 · 모름 0.8).
- 자동 실행: 해외 수요를 등록·엑셀로 올린 직후(`NEW_DEMAND`), 성과 카드를 검수 확정한 직후(`NEW_CARD`). `GAP_AUTO_RUN=false` 로 끈다.
  자동 실행이 실패해도 올리기·검수 확정은 그대로 저장된다 (서버 로그에만 남음).
- 갭은 모두 초안(DRAFT)이고 DEPT_REVIEWER/ADMIN 만 확정·기각한다 (DB 트리거). 이미 판정한 종류는 다시 초안으로 올리지 않고,
  확정된 갭이 다음 실행에서 안 나오면 `maybe_resolved_at`("해소 후보")에 시각을 남긴다. 예전 초안은 `SUPERSEDED`.
- 갭의 보안등급 = 해외 수요·근거 카드 중 가장 높은 등급 (DB 가 강제). 공개자료 수요라도 대내 카드가 근거면 대내.
- 기준값은 실행마다 `gap_run.rule_snapshot` 에 남는다. `POST /gaps/runs` 의 `rules` 로 한 번만 바꿔 볼 수 있다.

정답 사례(`전차파워팩_해외수요.xlsx` 의 `갭사례` 시트, G01~G04)로 재기:

```bash
EMBEDDER=bge_m3 python -m app.gap_eval all    # 해외 수요·K2 카드 적재 + 갭 분석 + 정답 비교 (재실행 안전)
```

## 신규 과제 기획 (기획 참고서)

`app/services/planning_brief.py`(판정, DB 없음) · `app/routers/planning.py`, 스키마 0029.
동향 하나와 가까운 성과 카드(갭 분석과 같은 짝으로 찾음, 열람 가능 + 비슷한 정도 `min_sim` 이상)를 과제별로 묶어 정리한다.

- 관련 과거 과제: 결과 구분(`project.outcome_code`), 성과·달성 성능, 한계·향후 과제(카드 미해결 항목), 평가 의견(`project_evaluation`).
- 요구 성능 비교: 지표명이 같은 과거 달성값 중 가장 잘 맞는 것 → 충족 / 부족(달성률) / 과거 자료 없음 / 단위 다름 / 서술형.
- 새 기획에 넣을 것 (이 순서): 실패 원인 먼저(전환 실패·중단 과제, 목표 미달 성능, 미흡 평가) → 성능 높이기 → 남은 숙제 풀기(우선순위 높음 또는 동향과 관련) → 평가 의견 반영 → 국산화(수입 품목) → 새로 개발 → 이어받기.
- `min_sim` 기본 0.45 는 BGE-M3 기준이다. 해시 임베더로 돌릴 때는 화면의 ‘덜 비슷한 과제도 보기’(0.35)나 더 낮은 값을 쓴다.
- 문서 등록(`POST /documents`, `/documents/upload`) 때 본문에서 과제번호·다른 번호·과제명(8글자 이상)을 찾아 `document_project_link` 에 남긴다. 공모서·사업 기획서나 과제가 여럿 나온 문서는 '실린 과제', 하나뿐이면 그 과제의 문서로 보고 문서의 과제·소관부서를 채운다. 시연용 합성 문서: `seeds/planning_docs/`.
- K2 파워팩 시연 자료(`seeds/overseas/국내성과_K2파워팩.json`)에 과제 결과 구분·평가 의견이 들어 있다 (평가 의견은 합성, 평가 주체에 표시).

## 매칭 로직 요약

1. 수요 패싯 임베딩 (기술수요·요구성능·적용환경·사업목적·기술요소별)
2. 후보 생성: 패싯 쌍별 HNSW 검색 (`ax.match_cards`) — 기술수요 ↔ 미해결 기술 / 핵심기술 / 기술원리, 요약 ↔ 요약
3. 후보 카드별로 모든 패싯 유사도를 정확히 다시 계산 (기술요소별 행은 제외)
4. 5개 기준 점수
   - TECH: 기술 패싯 유사도 중 최댓값
   - PERFORMANCE: 같은 지표의 달성/요구 비율 (없으면 패싯 유사도, 그것도 없으면 0.5)
   - TRL: 요구 범위 적합도 (미달 단계당 −0.25, 초과 단계당 −0.1)
   - ENVIRONMENT: 적용환경 유사도
   - PURPOSE: 사업목적 ↔ 카드 요약 유사도
5. 유형 신호
   - 후속형: 미해결 기술 유사도
   - 고도화형: 핵심기술 유사도 × 성능 격차
   - 전환형: 기술원리 유사도 × 다른 무기체계·사업트랙
   - 활용형: TRL·요구성능 충족
   - 사업화형: 기업·품목 연계 + 사업화 성격 사업트랙
   - 융합형: 기술요소별 최적 카드가 2개 이상
6. 대표 유형의 `linkage_rule` 가중치로 종합점수를 계산한다. 기준 미만인 추천도 지우지 않고 `is_excluded` 와 사유를 남겨 보존한다.
7. 근거: 카드 필드 근거 + 원과제 문서 RAG 검색 결과(요청자 권한 적용)를 연결한다.
8. 부서·기업 후보
   - 소관부서: 원과제 부서
   - 협업부서: 수요 요청부서, 결합된 다른 성과의 부서
   - 기업: AI 추정 관계는 '추가 확인 필요' 항목으로 생성한다.

`HashEmbedder` 는 의미를 이해하지 않는 테스트용 임베더다. 추천 품질 평가는 반드시 `EMBEDDER=bge_m3` 로 한다.

## 합성 데이터로 추천 적중률 재기

공개 사례(국기연·방사청 보도자료, 공개 논문)를 뼈대로 만든 합성 과제 60개와 기획수요 15개, 정답 연계 17쌍을 넣고
기획수요마다 매칭을 돌려 정답이 상위 5·10 안에 드는지 잰다 (제안서 목표 80%). 자세한 내용은 `seeds/synthetic/README.md`.

```bash
python -m app.synthetic all     # 서버를 띄우지 않아도 된다. EMBEDDER=bge_m3 로 잴 것
```

## LLM 연계이유 문장 (선택)

`RATIONALE_GENERATOR` 기본값은 `template`(규칙 템플릿 문장, **외부 전송 없음**)이다.
`auto` = API 키가 있으면 LLM, 없으면 템플릿 / `llm` = 키 유무와 관계없이 항상 시도.
LLM 은 추천 저장·근거 연결 뒤에 **그 추천에 연결된 원문 근거 인용문과 점수, 수요·카드 요약(제목·TRL·성능·미해결 기술)**을
입력으로 연계이유를 다시 쓴다. Anthropic·OpenAI 제공자는 이 내용을 **외부 API 로 전송**한다.
켜져 있는지는 `curl localhost:8000/health` 의 `rationale.external` 로 확인한다 (`false` 면 외부 전송 없음).

```bash
pip install -e ".[llm]"
export RATIONALE_GENERATOR=auto       # 명시적으로 켜야 한다
export ANTHROPIC_API_KEY=sk-ant-...   # 모델 기본값 LLM_MODEL=claude-opus-5-5

# 또는 OpenAI
export LLM_PROVIDER=openai
export OPENAI_API_KEY=sk-proj-...     # 모델 기본값 gpt-5.5 (LLM_MODEL 로 변경)
```

- `LLM_EFFORT` 는 Anthropic 의 `effort`, OpenAI 의 `reasoning_effort` 로 보낸다. 추론 모델이 아닌 OpenAI 모델(gpt-4.1 등)은 `LLM_EFFORT=` 로 비운다.

- 재매칭 없이 다시 만들기: `POST /recommendations/{id}/rationale` (PLANNER, 검토 종료 전 추천만).
  추천 상세 화면의 "AI 연계이유 다시 생성" 버튼이 이 API 를 부른다. LLM 이 꺼져 있으면 409.
- 추천 조회 응답의 `rationale_generation` = `{status: OK|FALLBACK|null, generator, error}`.
- 스모크: 서버에 키를 넣고 `SMOKE_LLM=1 ./scripts/smoke_test.sh` 로 실제 생성까지 확인.

- 템플릿 문장은 항상 `recommendation.rationale` 에 저장되고, LLM 문장은 `rationale_llm` 에 따로 저장된다 (0017).
- 다음 경우 LLM 문장을 버리고 템플릿을 쓴다 (`rationale_meta.status = FALLBACK`, 사유 기록):
  키 없음·인증 실패·타임아웃·429/5xx·모델 거절·응답 잘림, 그리고 **근거 검증 실패** —
  입력(근거·점수)에 없는 수치를 쓰거나, 없는 근거 번호를 인용하거나, 근거가 있는데 인용하지 않은 경우.
- 인용 `[E1]` 은 화면에 `[근거: 문서명 절 p.쪽]` 으로 바뀐다. 개발필요사항은 규칙 산출값 그대로다.
- 열람권한: LLM 문장에는 근거 문서 내용이 녹아 있으므로, 입력 근거 문서를 **모두 열람할 수 있는 사용자에게만**
  LLM 문장을 보여 주고 나머지에게는 템플릿 문장을 보여 준다 (`ax.rationale_for_user`, API 응답 `rationale_source`).
- `LLM_EVIDENCE_MAX_SECURITY`(기본 INTERNAL)를 넘는 보안등급 문서의 원문은 외부 LLM 에 보내지 않는다.
  수요나 출처 성과카드 자체가 이 등급을 넘으면 그 추천은 아예 호출하지 않고 템플릿을 쓴다 (0018 점검 때 추가).
  폐쇄망 운영 시에는 `app/services/llm.py` 에 사내 LLM 클라이언트를 추가하고 `LLM_PROVIDER` 로 선택한다.
- 제외 후보(`is_excluded`)는 호출하지 않는다. 실행별 성공/대체 건수는 `match_run.params.rationale_llm` 에 남는다.
- Bedrock·Vertex 처럼 서버측 대체 모델(`fallbacks`)을 지원하지 않는 경로에서는 `LLM_SERVER_FALLBACK=false`.
