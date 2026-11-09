# relay-ax-db

국방 R&D 성과연계·이어달리기 AX PoC 의 PostgreSQL 16 + pgvector 스키마 (프레임워크 중립 순수 SQL).

```
db/migrations/   0001~0015 순번 마이그레이션 (파일별 단일 트랜잭션)
db/optional/     IVFFlat 인덱스 대안
db/tests/        스모크 테스트 (샘플 데이터 → 전체 흐름 검증 → ROLLBACK)
seeds/          init_test_data.sql (부서·사용자 1~5·역할·기관·사업·과제 최소 시드, 재실행 안전)
scripts/         migrate.sh (psql 기반 실행기, 체크섬 검증), smoke_test.sh (curl API 스모크 테스트)
docs/ERD.md      ERD·설계 설명·가정·요구사항 매핑
backend/         FastAPI 백엔드 (매칭·추천 엔진, HITL 검토 API) — backend/README.md
docs/navigator.md Navigator(기업 대상 서비스) 단계별 설명 — 1단계: 기업 프로필·관리 링크
frontend/        Vite + React 역할별 화면 (역할 선택 로그인, 관리자·작업자 대시보드) — frontend/README.md
```

```bash
DATABASE_URL=postgres://user:pass@host:5432/relay_ax ./scripts/migrate.sh
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/tests/smoke_test.sql
```

설계 가정(임베딩 1024차원, cosine, HNSW 등)은 `docs/ERD.md` 1장 참조.

## 로컬 API 스모크 테스트

```bash
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/relay_ax
./scripts/migrate.sh                                                       # 1. 스키마
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f seeds/init_test_data.sql     # 2. 시드 (여러 번 실행해도 안전)
(cd backend && uvicorn app.main:app --port 8000) &                          # 3. 서버 (기본 EMBEDDER=hash)
BASE_URL=http://localhost:8000 ./scripts/smoke_test.sh                     # 4. 7단계 흐름 검증 (curl, jq 필요)
```

시드 사용자(`X-User-Id`): 1 PLANNER · 2 DEPT_REVIEWER · 3 EXPERT · 4 CURATOR · 5 VIEWER.
스모크 스크립트는 단계마다 HTTP 상태코드를 확인해 PASS/FAIL 을 찍고, 하나라도 실패하면 종료 코드 1 을 돌려준다.

## 프론트엔드 시연

위 1~3단계로 백엔드를 띄운 뒤 `cd frontend && npm install && npm run dev` → http://localhost:5173 에서 역할을 골라 로그인한다. 자세한 내용과 시연 순서는 `frontend/README.md`.
