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
    embedding.py     Embedder(Hash/BGE-M3), 카드·수요 패싯 텍스트, 임베딩 동기화(sha256 변경 감지)
    scoring.py       5개 기준 점수, 6대 연계유형 분류, 융합형 판정 (순수 함수)
    matching.py      수요→성과 매칭 실행, 추천·점수·근거·부서/기업 후보 저장
    rationale.py     연계이유·개발필요사항 문장 (템플릿 + LLM 연계이유 생성·근거 검증)
    llm.py           LLM 제공자 클라이언트 (Anthropic Claude, 교체 가능)
```

## 주요 API

| 메서드 | 경로 | 역할 | 설명 |
|---|---|---|---|
| POST | `/documents` | CURATOR, PLANNER | 파싱·청킹된 문서 등록 + 청크 임베딩 |
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

## LLM 연계이유 문장 (선택)

기본(`RATIONALE_GENERATOR=template`)은 규칙 템플릿 문장이다. `llm` 으로 바꾸면 추천 저장·근거 연결 뒤에
**그 추천에 연결된 원문 근거 인용문과 점수만**을 입력으로 LLM 이 연계이유를 다시 쓴다.

```bash
pip install -e ".[llm]"
export RATIONALE_GENERATOR=llm ANTHROPIC_API_KEY=sk-ant-...   # 모델 기본값 LLM_MODEL=claude-opus-5-5
```

- 템플릿 문장은 항상 `recommendation.rationale` 에 저장되고, LLM 문장은 `rationale_llm` 에 따로 저장된다 (0017).
- 다음 경우 LLM 문장을 버리고 템플릿을 쓴다 (`rationale_meta.status = FALLBACK`, 사유 기록):
  키 없음·인증 실패·타임아웃·429/5xx·모델 거절·응답 잘림, 그리고 **근거 검증 실패** —
  입력(근거·점수)에 없는 수치를 쓰거나, 없는 근거 번호를 인용하거나, 근거가 있는데 인용하지 않은 경우.
- 인용 `[E1]` 은 화면에 `[근거: 문서명 절 p.쪽]` 으로 바뀐다. 개발필요사항은 규칙 산출값 그대로다.
- 열람권한: LLM 문장에는 근거 문서 내용이 녹아 있으므로, 입력 근거 문서를 **모두 열람할 수 있는 사용자에게만**
  LLM 문장을 보여 주고 나머지에게는 템플릿 문장을 보여 준다 (`ax.rationale_for_user`, API 응답 `rationale_source`).
- `LLM_EVIDENCE_MAX_SECURITY`(기본 INTERNAL)를 넘는 보안등급 문서의 원문은 외부 LLM 에 보내지 않는다.
  폐쇄망 운영 시에는 `app/services/llm.py` 에 사내 LLM 클라이언트를 추가하고 `LLM_PROVIDER` 로 선택한다.
- 제외 후보(`is_excluded`)는 호출하지 않는다. 실행별 성공/대체 건수는 `match_run.params.rationale_llm` 에 남는다.
- Bedrock·Vertex 처럼 서버측 대체 모델(`fallbacks`)을 지원하지 않는 경로에서는 `LLM_SERVER_FALLBACK=false`.
