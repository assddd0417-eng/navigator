# 국방 R&D 성과연계·이어달리기 AX — 데이터베이스 설계 (ERD 설명서)

- 대상: PostgreSQL 16 + pgvector (스키마 `ax`)
- 범위: PoC 백엔드의 저장 구조 전체 (성과 활용카드 → 신규 기획수요 비교 → 6대 연계유형 추천 → RAG 근거 → 담당부서·전문가 검토 → 통합기획 → 실제 연계성과 축적 → PoC 검증)
- 근거 자료: 제안서 「국방 R&D 성과연계·이어달리기 AX」, 「데이터 요구사항 정의서」(109개 항목, 기준정보 Master 14종)
- 검증: PostgreSQL 16.15 + pgvector 0.6.0 에서 전체 마이그레이션 적용, 재실행(멱등), 스모크 테스트(`db/tests/smoke_test.sql`) 통과

---

## 1. 설계 가정 (확정 필요)

| # | 항목 | 가정값 | 바뀌면 영향 |
|---|------|--------|-------------|
| A1 | 임베딩 모델·차원 | **1024차원**, 다국어 모델(BGE-M3 계열), 폐쇄망 자체 구동 | `vector(1024)` 컬럼·HNSW 인덱스 재생성 + 전체 재임베딩 (새 마이그레이션) |
| A2 | 거리 척도 | cosine (`vector_cosine_ops`) | 정규화 벡터면 inner product(`vector_ip_ops`)로 교체 가능 |
| A3 | 벡터 인덱스 | **HNSW 기본** (m=16, ef_construction=64), IVFFlat 은 `db/optional/` 대안 | 청크 수백만 건 이상이면 IVFFlat 검토 |
| A4 | pgvector 버전 | ≥ 0.5.0 필요 (HNSW). **0.8 이상 권장** (필터 검색 시 iterative scan) | 0.7 이상이면 `halfvec`로 저장공간 절반 가능 |
| A5 | 한국어 키워드 검색 | 형태소 분석기 없이 `simple` tsvector + `pg_trgm` | mecab-ko / pg_bigm 도입 시 인덱스 교체 |
| A6 | 보안등급 체계 | 공개(0)·내부(1)·대외비(2)·비밀(3) 4단계 | 원천시스템 실제 등급으로 `code_security_level` 교체 |
| A7 | 식별자 | 내부 PK 는 `bigint identity`, 원천 ID 는 `*_no`/`*_code` + `external_id_map` | 외부 API 노출용 UUID 필요 시 컬럼 추가 |
| A8 | 원본 파일 | DB 에는 메타데이터·청크만, 원본은 오브젝트 스토리지(`storage_uri`) | — |
| A9 | 비밀 등급 원문 | PoC 는 비식별/공개 가능 자료 위주 (`is_deidentified`) | 운영 시 망분리·암호화 정책 추가 |
| A10 | 6대 연계유형 초기 가중치 | `linkage_rule` v1 시드값 (예: 후속형 기술 0.45) | PoC 검증 결과로 v2 등록 후 활성화 |

---

## 2. 전체 구조 한눈에 보기

```
[기준정보]  기관·부서·사용자 / 기술분류·무기체계·품목·BOM / 동의어 사전 / 사업트랙·적용조건 / 연계규칙
     │
[원천]      과제(Project) ──< 원문 문서 ──< 조항(Section) ──< 청크(Chunk) ──< 근거(Evidence)
     │                                                     │
[구조화]    성과 활용카드 ──< 핵심기술·성능·미해결항목·연구성과   (각 필드 ↔ 근거)
            └─ 관계: 무기체계·품목·기업·사업트랙 (불확실 = '추가 확인 필요')
     │
[수요]      신규 기획수요 ──< 요구성능·기술요소·무기체계·품목
     │
[벡터]      청크/카드/수요/기업기술/사업목적 임베딩 (패싯별 부분 HNSW)
     │
[추천]      매칭 실행 ──< 추천 ──< 출처카드·기준별 점수·유형확률·RAG 근거·부서/기업/품목 후보
     │
[HITL]      검토 배정 ──< 검토 의견/최종판정 (추가 전용) + 상태 이력 + 감사 로그
     │
[통합기획]  검토표·초안·회의 → 연계 실행 결과 (→ 신규 과제 → 다시 성과카드: 순환)
     │
[PoC 검증]  정답 후보·Top-K 포함률·업무시간·만족도
```

---

## 3. 핵심 ERD

```mermaid
erDiagram
    program ||--o{ project : "사업트랙"
    department ||--o{ project : "소관부서"
    organization ||--o{ project_participant : ""
    project ||--o{ project_participant : "주관/참여"
    project ||--o{ project_relation : "선행·후속(실제 이어달리기 사례)"

    project ||--o{ source_document : ""
    source_document ||--o{ document_section : "조항"
    source_document ||--o{ document_chunk : ""
    document_section ||--o{ document_chunk : ""
    document_chunk ||--o{ evidence : "인용 위치"
    document_chunk ||--|| chunk_embedding : "vector(1024)"

    project ||--o{ achievement_card : "성과 활용카드"
    achievement_card ||--o{ card_technology : "핵심기술·기술원리"
    achievement_card ||--o{ card_performance : "달성성능"
    achievement_card ||--o{ card_open_issue : "미해결·후속연구"
    achievement_card ||--o{ card_outcome : "논문·특허"
    achievement_card ||--o{ card_field_evidence : ""
    evidence ||--o{ card_field_evidence : ""
    achievement_card ||--o{ card_embedding : "패싯별 vector"
    achievement_card }o--o{ weapon_system : "card_weapon_system"
    achievement_card }o--o{ item : "card_item"
    achievement_card }o--o{ organization : "card_company"
    achievement_card }o--o{ program : "card_program"

    planning_demand ||--o{ demand_performance_req : "요구성능"
    planning_demand ||--o{ demand_embedding : "패싯별 vector"

    planning_demand ||--o{ match_run : ""
    match_run ||--o{ recommendation : ""
    code_linkage_type ||--o{ recommendation : "6대 유형"
    recommendation ||--|{ recommendation_source_card : "융합형 2개+"
    achievement_card ||--o{ recommendation_source_card : ""
    recommendation ||--o{ recommendation_score : "5개 기준"
    recommendation ||--|{ recommendation_evidence : "근거 1개+"
    evidence ||--o{ recommendation_evidence : ""
    recommendation ||--o{ recommendation_department : "담당/협업"
    recommendation ||--o{ recommendation_company : ""
    recommendation ||--o{ confirmation_item : "추가 확인"

    recommendation ||--o{ review_assignment : ""
    review_assignment ||--o{ review_decision : ""
    recommendation ||--o{ review_decision : "최종판정"
    recommendation ||--o{ recommendation_status_history : ""

    recommendation ||--o{ relay_review_sheet_item : ""
    relay_review_sheet ||--o{ relay_review_sheet_item : "검토표"
    recommendation ||--o{ linkage_execution : "실제 연계"
    linkage_execution }o--o| project : "신규 과제"
```

---

## 4. 마이그레이션 구성

| 파일 | 내용 | 주요 테이블 |
|------|------|-------------|
| `0001_extensions_and_schema` | pgvector·pg_trgm, `ax` 스키마, 공통 함수 | `schema_migrations`, `set_updated_at()`, `current_app_user()` |
| `0002_code_tables` | 업무 코드 (시드 포함) | `code_linkage_type`(6대 유형), `code_program_type`, `code_project_status`, `code_dev_stage`, `code_security_level`, `code_document_type`, `code_outcome_type`, `code_source_system`, `code_review_decision` |
| `0003_org_users_access` | 기관/부서 Master, 권한 Master | `organization`, `department`, `app_user`, `app_role`, `user_role`, `department_access_grant` |
| `0004_reference_masters` | 기술·체계·품목·동의어·ID 매핑·사업트랙·규칙 | `tech_taxonomy`, `weapon_system`, `item`, `item_bom`, `term_synonym`, `external_id_map`, `program`, `program_condition`, `linkage_rule` |
| `0005_companies_items` | 기업 Master 확장 | `company_profile`, `company_technology`, `company_item`, `export_prospect` |
| `0006_projects` | 과제 Master | `project`, `project_participant`, `project_member`, `project_relation` |
| `0007_documents_chunks` | Source Master, RAG 저장소 | `source_document`, `document_section`, `document_chunk`, `evidence`, `document_access_grant` |
| `0008_achievement_cards` | 성과 활용카드·관계 그래프 | `achievement_card`, `card_technology`, `card_performance`, `card_open_issue`, `card_outcome`, `card_weapon_system`, `card_item`, `card_company`, `card_program`, `card_field_evidence`, `card_source_document` |
| `0009_planning_demands` | 기획수요 Master | `planning_demand`, `demand_performance_req`, `demand_technology`, `demand_weapon_system`, `demand_item` |
| `0010_embeddings` | 임베딩·HNSW | `embedding_model`, `chunk_embedding`, `card_embedding`, `demand_embedding`, `company_tech_embedding`, `program_embedding` |
| `0011_matching_recommendations` | AI 추천 | `match_run`, `recommendation`, `recommendation_source_card`, `recommendation_score`, `recommendation_linkage_score`, `recommendation_evidence`, `recommendation_department`, `recommendation_company`, `recommendation_item`, `confirmation_item` |
| `0012_review_workflow_audit` | HITL·검토 이력·감사 | `review_assignment`, `review_decision`, `review_comment`, `recommendation_status_history`, `audit_log` |
| `0013_integrated_planning` | 통합기획 | `planning_meeting`, `relay_review_sheet(_item)`, `planning_draft(_evidence)`, `meeting_decision`, `linkage_execution` |
| `0014_poc_evaluation` | PoC 검증 | `eval_case`, `eval_ground_truth`, `eval_run`, `eval_run_case`, `work_time_measurement`, `satisfaction_survey` |
| `0015_functions_views` | 조회 함수·KPI 뷰 | `can_read_document()`, `search_chunks()`, `match_cards()`, `v_recommendation_overview`, `v_recommendation_evidence`, `v_review_queue`, `v_kpi_*`, `v_eval_topk_hits` |
| `0016_embedding_model_per_embedder` | 임베더별 벡터 분리 | `embedding_model` 에 hash 모델 행 추가·기존 벡터 이관, `match_cards()` 활성 모델 조건 |
| `0019_navigator_company_profile` | Navigator 기업 프로필 확장 (docs/navigator.md) | `company_profile` 칸 추가, `company_patent`, `company_certification`, `code_certification_type`, `company_credit_rating`, `company_rnd_history`, `company_access_link` |
| `0020_navigator_field_sources` | Navigator 출처 기록 | `external_source`, `external_fetch_job`, `external_raw_record`, `company_field_source`, `v_company_field_compare` |

합계: 테이블 90개, 뷰 7개.

---

## 5. 영역별 설계 설명

### 5.1 코드 테이블 vs ENUM
6대 연계유형·사업유형·보안등급 등 **업무 코드는 코드 테이블**로 두었다. 한글 명칭·설명·정렬순서를 함께 관리하고, 운영 중 DDL 없이 코드를 추가·비활성화할 수 있기 때문이다. `code_linkage_type` 은 추천 로직에 필요한 메타데이터도 가진다.

| 코드 | 명칭 | `min_source_cards` | `requires_company` |
|------|------|---|---|
| FOLLOW_UP | 후속형 | 1 | |
| ADVANCEMENT | 고도화형 | 1 | |
| TRANSITION | 전환형 | 1 | |
| CONVERGENCE | 융합형 | **2** | |
| UTILIZATION | 활용형 | 1 | |
| COMMERCIALIZATION | 사업화형 | 1 | ✓ |

검토 상태 같은 시스템 내부 상태값은 각 테이블의 `CHECK` 제약으로 관리한다.

### 5.2 성과 활용카드
- 카드 1장 = 과제의 대표 성과 1건 (`achievement_card`). 과제 1건에 카드 여러 장이 가능하다.
- 정의서 13~28번 항목을 하위 테이블로 구조화했다.
  - 핵심기술·기술원리 → `card_technology` (대표 기술 1개는 부분 unique 인덱스로 보장)
  - 달성성능·시험조건·미달성 성과 → `card_performance` (목표값/달성값/`is_achieved`)
  - 미해결 기술항목·미달성 항목·후속 연구 필요사항 → `card_open_issue` (**후속형 추천의 핵심 입력**). 후속 과제로 해결되면 `is_resolved` 와 `resolved_by_project_id` 를 기록한다.
  - 주요 연구성과·지식재산권 → `card_outcome`
- **최신성**: `has_follow_up_research`, `latest_utilization_at`, `revision` 컬럼을 둔다. 내용이 갱신되면 `revision` 을 올리고, 이전 값은 `audit_log` 에 남는다. 임베딩에는 `card_revision` 을 기록해 재임베딩이 필요한지 판단한다.
- **불확실한 관계**: 성과-무기체계/품목/기업/사업트랙 관계 테이블은 모두 `relation_status`(CONFIRMED / NEEDS_CONFIRMATION / REJECTED), `origin`(SOURCE/AI/HUMAN), `confidence` 를 가진다. AI가 추정한 기업 관계는 기본값이 '추가 확인 필요'다.
- **원문 근거 연결**: `card_field_evidence` 가 카드의 어떤 행·필드가 어떤 원문 위치(`evidence`)에서 나왔는지 기록한다.

### 5.3 원문·RAG 근거
- `source_document`: 문서유형·버전·작성일·이전 버전(`supersedes_id`)·`is_latest`·보안등급·소관부서·비식별 여부를 가진다 (정의서 29~35, 98, 101, 109번).
- `document_section`: 장·절·**조항** 계층 (`section_no` 예: '제3조', '4.3').
- `document_chunk`: 검색 단위. 페이지 범위와 `location`(문단·표·셀·bbox, JSON)을 가진다. 키워드 검색용 `tsv` 생성 컬럼과 trigram 인덱스를 함께 두어 하이브리드 검색이 가능하다.
- `evidence`: 청크보다 좁은 **인용 단위**. 문서·조항·페이지·청크·인용문을 묶은 것으로, 카드 필드·추천·통합기획 초안이 공통으로 참조한다.

### 5.4 임베딩과 벡터 인덱스
- **패싯 임베딩**: 카드와 수요를 관점별로 나눠 임베딩한다. 연계유형마다 비교할 관점이 다르기 때문이다.

| 연계유형 | 수요 패싯 | 카드 패싯 (주 비교 대상) |
|----------|-----------|--------------------------|
| 후속형 | TECH_NEED | OPEN_ISSUE (미해결 기술) |
| 고도화형 | TECH_NEED, PERFORMANCE | CORE_TECH, PERFORMANCE |
| 전환형 | TECH_NEED, APPLICATION_ENV | PRINCIPLE, APPLICATION_ENV |
| 융합형 | 기술요소별 TECH_NEED (`demand_technology`) | CORE_TECH (요소별로 서로 다른 카드) |
| 활용형 | PERFORMANCE, APPLICATION_ENV | PERFORMANCE |
| 사업화형 | PURPOSE | SUMMARY + `company_tech_embedding` |

- **패싯별 부분 HNSW 인덱스** (`WHERE facet = 'OPEN_ISSUE'` 등): 하나의 큰 인덱스에서 facet 으로 거르면 상위 K개가 모자랄 수 있는데, 부분 인덱스를 쓰면 그 문제가 없다. `match_cards()` 는 패싯을 리터럴로 넣은 동적 SQL 로 실행해 부분 인덱스가 선택되게 했다 (스모크 테스트에서 `Index Scan using card_embedding_hnsw_open_issue` 확인).
- `embedding_model` 에 활성 모델을 하나만 두고, 모든 임베딩 행이 `model_id` 를 가진다. 임베더마다 모델 행이 따로 있다(0016: 개발용 `relay-ax/hash-ngram`, 실제 `BAAI/bge-m3`). 백엔드가 시작할 때 `EMBEDDER` 설정에 맞는 행을 활성으로 바꾸고, 모든 벡터 검색은 활성 모델 벡터만 본다. 모델을 바꾼 뒤에는 `python -m app.reembed` 로 재임베딩하며, 이때 다른 모델 벡터는 지운다(HNSW 인덱스가 모델 구분 없이 하나라서 남겨 두면 근접 후보 자리를 차지한다). 차원이 다르면 새 마이그레이션으로 컬럼 타입을 바꿔야 한다.
- 사업트랙 목적 임베딩은 건수가 적어 인덱스 없이 전수 비교한다.

### 5.5 매칭·추천
- `match_run`: 매칭 1회 실행. 실행 유형(수요→성과, 성과→수요, 성과→사업트랙, 성과→기업, 정기 점검, 평가), 임베딩 모델, LLM, **규칙 스냅샷**(`rule_snapshot`), 파라미터를 저장해 결과를 재현할 수 있다.
- `recommendation`: 연계 후보 1건이다.
  - 연계 대상은 신규 수요, 사업트랙, 진행 중인 타 부서 과제 중 하나 이상이다.
  - AI 판정 연계유형과 순위, 종합점수, 신뢰도, 연계이유, 개발필요사항을 담는다.
  - 비추천·제외 후보는 지우지 않고 `is_excluded` + 사유로 보존한다 (정의서 56번).
  - 최종판정 결과(`final_*`)는 검토 트리거가 채운다.
- `recommendation_score`: 5개 기준(기술 유사도·성능·TRL·적용환경·사업목적 적합도)별 점수, 가중치, 산출방법을 담는다 (정의서 49~54번).
- `recommendation_linkage_score`: 6대 유형 분류 확률. 대표 유형 외에 차순위 유형도 검토할 수 있다.
- `recommendation_evidence`: RAG 근거. 근거가 어느 쪽 자료인지(성과카드/수요/사업트랙/기업)와 근거 역할(지지/대조/조건/제외), 대응 기준, 검색 점수를 담는다.
- `recommendation_department` / `_company` / `_item`: 담당·협업부서, 기업, 품목 후보다. 기업은 "자동 선정"이 아니라 근거가 있는 후보로만 제시한다는 원칙에 따라 기본 상태가 '추가 확인 필요'다.
- **검토 진입 가드** (DB 트리거): 추천이 `GENERATED` 에서 검토 단계로 넘어가려면
  1. 원문 근거가 1건 이상 있어야 한다 → **근거 연결률 100%** 목표를 구조적으로 보장
  2. 출처 성과카드 수가 연계유형 최소치 이상이어야 한다 → 융합형은 2개 이상

### 5.6 Human-in-the-Loop 검토
```
GENERATED ──(검토 배정)──> ASSIGNED ──(검토 의견)──> IN_REVIEW ──(담당부서 최종판정)──> DECIDED
                                   └─(추가 확인 필요)─> NEEDS_INFO ─┘
                       (언제든) ──> WITHDRAWN
```
- `review_assignment`: 담당부서(DEPT_OWNER)·협업부서·전문가(EXPERT)를 배정한다. 사용자 단위나 부서 단위로 배정할 수 있다.
- `review_decision`: **추가 전용**. 판정(채택/보류/제외/추가 확인 필요), 연계유형 수정, 의견, 그리고 PoC 품질평가 항목(관련성·근거 적절성·개발필요사항 정확성·저관련 여부)을 담는다. 재판정은 `supersedes_id` 로 새 행을 쌓는다.
- DB 가 강제하는 원칙:
  - **최종판정은 `DEPT_REVIEWER` 또는 `ADMIN` 역할을 가진 사람만** 할 수 있다 (AI·전문가 단독 불가).
  - 최종판정에는 '추가 확인 필요'를 쓸 수 없다.
  - 배정 전이거나 철회된 추천에는 판정할 수 없다.
- 상태 전이는 트리거가 자동으로 처리한다 (배정 → ASSIGNED, 의견 → IN_REVIEW, 최종 → DECIDED + `final_*` 반영).

### 5.7 검토 이력·감사 로그
- `recommendation_status_history`: 추천 상태 변경 이력 (누가, 언제, 무엇에서 무엇으로, 사유). 추가 전용이다.
- `audit_log`: 카드·수요·추천·검토·권한 등 24개 테이블의 행 단위 변경 전/후 JSON, 변경 컬럼, 행위자, 요청 ID 를 남긴다. 추가 전용이다.
- 행위자 식별: 백엔드가 트랜잭션마다 아래처럼 설정한다 (프레임워크 무관).
  ```sql
  SET LOCAL app.current_user_id = '42';
  SET LOCAL app.request_id = '7f0c...';      -- 선택
  SET LOCAL app.status_reason = '근거 보강 요청'; -- 선택: 상태 이력 사유
  ```
- 상위 행 삭제에 따른 FK CASCADE 삭제는 허용한다 (PoC 재실행으로 `match_run` 을 지울 때). 삭제된 판정 내용은 `audit_log` 에 남는다. `audit_log` 자체는 어떤 경우에도 수정·삭제할 수 없다.

### 5.8 보안·권한
- `can_read_document(user, doc)` 는 다음 두 조건을 모두 볼 때 참이다.
  1. 사용자 등급 ≥ 문서 보안등급
  2. 다음 중 하나: 소관부서 미지정, 본인 부서 소관, 부서 열람권한(`department_access_grant`), 문서 개별 허용(`document_access_grant`)
- `search_chunks()` 는 이 함수로 결과를 거른다. HNSW 탐색 뒤에 필터가 적용되므로 `p_k × p_oversample` 만큼 먼저 가져온 다음 거른다. pgvector 0.8 이상이면 `hnsw.iterative_scan` 으로 대체할 수 있다.
- 운영 단계에서는 Row Level Security(RLS) 정책으로 확장하는 것을 권장한다 (PoC 는 함수 기반).

### 5.9 통합기획·순환 축적
- `relay_review_sheet(_item)`: 부서별 이어달리기 후보 검토표. 항목마다 생성 시점의 **스냅샷**(JSON)을 저장해 회의자료를 그대로 재현할 수 있다.
- `planning_draft(_evidence)`: LLM 이 생성한 통합기획 초안(버전 관리)과 각주 근거.
- `planning_meeting` / `meeting_decision`: 회의와 결정·후속조치.
- `linkage_execution`: 실제로 과제화·사업화·수출·기술이전된 결과. `resulting_project_id` 로 신규 과제와 연결되고, 그 과제가 다시 성과카드를 만들면 **"기존 성과 → 신규 과제 → 성과 축적"** 순환이 완성된다. `discovered_by_ax` 로 AX 가 신규 발굴한 연계를 집계한다.

### 5.10 PoC 검증과 KPI 뷰
| 정량목표 | 산출 위치 |
|----------|-----------|
| 전문가 주요 후보 상위 추천 포함률 ≥ 80% | `v_kpi_eval.major_topk_recall_pct` (`eval_ground_truth` × `recommendation` 순위) |
| 추천결과 원문 근거 연결률 100% | `v_kpi_recommendation.evidence_coverage_pct` (+ 검토 진입 가드) |
| 추천후보 최종 검토율 100% | `v_kpi_recommendation.final_review_pct` |
| 조사시간 ≥ 70% / 검토자료 작성시간 ≥ 60% 단축 | `v_kpi_work_time.reduction_pct` (`work_time_measurement` 수작업 대 AX) |
| 관련성 낮은 후보 비율, 근거 적절성, 개발필요사항 정확성 | `review_decision` 평가 항목 집계 |
| 연계유형 분류 정확도 | `v_kpi_eval.linkage_type_accuracy_pct` |
| 추가 연계후보 수 | `work_time_measurement.candidates_found`, `linkage_execution.discovered_by_ax` |

과거 실제 이어달리기 사례는 `project_relation.is_actual_relay` 로 표시하고, `eval_case.project_relation_id` 로 검증 케이스와 연결한다.

---

## 6. 데이터 요구사항 정의서 ↔ 테이블 매핑

| 정의서 영역 (항목 번호) | 테이블 |
|---|---|
| 과제 기본 (1~12) | `project`, `project_participant`, `project_member`, `program`, `code_project_status`, `code_dev_stage` |
| 성과 활용카드 (13~28) | `achievement_card`, `card_technology`, `card_performance`, `card_open_issue`, `card_outcome`, `card_weapon_system`, `card_item` (+ `item_bom`) |
| 문서·근거 (29~35) | `source_document`, `document_section`, `document_chunk`, `evidence`, `card_field_evidence` |
| 신규 수요 (36~44) | `planning_demand`, `demand_performance_req`, `demand_technology`, `demand_weapon_system`, `demand_item` |
| 사업트랙 (45~47) | `program`, `program_condition`, `source_document`(사업공고 유형) |
| 연계 분석 (48~56) | `code_linkage_type`, `linkage_rule`, `match_run`, `recommendation`, `recommendation_score`, `recommendation_linkage_score`, `recommendation_evidence` |
| 기업·품목 (57~65) | `organization`, `company_profile`, `company_technology`, `company_item`, `export_prospect`, `recommendation_company`, `recommendation_item` |
| 관계·그래프 (66~73) | `card_*` 관계 테이블, `project_relation` |
| 추천·검토 (74~80) | `recommendation_department`, `review_assignment`, `review_decision`, `recommendation_status_history`, `audit_log`, `confirmation_item` |
| 통합기획 (81~84) | `relay_review_sheet(_item)`, `planning_draft`, `planning_meeting`, `meeting_decision`, `linkage_execution` |
| 검증/PoC (85~97) | `eval_case`, `eval_ground_truth`, `eval_run(_case)`, `work_time_measurement`, `satisfaction_survey`, KPI 뷰 |
| 보안·권한 (98~101) | `code_security_level`, `app_user`, `user_role`, `department_access_grant`, `document_access_grant`, `source_document.is_deidentified` |
| 기준정보 (102~109) | `external_id_map`, `tech_taxonomy`, `weapon_system`, `item`, `department`, `organization`, `term_synonym`, `program`, `source_document` |

---

## 7. 실행 방법

```bash
# 1) 마이그레이션 적용 (멱등, 파일별 단일 트랜잭션, 체크섬 검증)
DATABASE_URL=postgres://user:pass@host:5432/relay_ax ./scripts/migrate.sh

# 2) 스모크 테스트 (샘플 데이터로 전체 흐름 검증 후 ROLLBACK)
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/tests/smoke_test.sql
```

벡터 검색 세션 파라미터 예시:
```sql
SET hnsw.ef_search = 100;   -- 재현율↑ / 속도↓ (기본 40)
SELECT * FROM ax.match_cards(1, 'TECH_NEED', 'OPEN_ISSUE', 20);          -- 후속형 후보
SELECT * FROM ax.search_chunks(:query_vec, :user_id, 10, ARRAY['FINAL_REPORT']);  -- RAG 근거
```

Flyway 를 쓰게 되면 파일명을 `V0001__extensions_and_schema.sql` 형식으로 바꾸고 `schema_migrations` 는 쓰지 않으면 된다. 각 파일에는 트랜잭션 구문(BEGIN/COMMIT)을 넣지 않았다.

---

## 8. 열린 쟁점 (다음 단계에서 결정)

1. **임베딩 모델 확정**: 폐쇄망 구동 여부와 GPU 자원에 따라 모델과 차원(A1)을 정한다.
2. **pgvector 버전**: 운영 DB 에 0.8 이상을 설치할 수 있는지 확인한다 (iterative scan, halfvec).
3. **보안등급·권한 원천 연동**: PMS/DTiMS/DSIS 권한을 `department_access_grant` 로 가져오는 주기와 방식.
4. **한국어 검색 품질**: 형태소 분석(mecab-ko)이나 pg_bigm 도입 여부. 동의어 사전(`term_synonym`)을 쿼리 확장에 쓰는 방식.
5. **카드 버전 관리 수준**: 지금은 `revision` + 감사 로그로 관리한다. 카드 스냅샷 테이블이 필요한지 판단해야 한다.
6. **RLS 도입 시점**: PoC 이후 운영 전환 시점.
