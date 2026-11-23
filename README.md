# Navigator

기업이 사업자번호로 지원할 수 있는 국방 지원사업 공고를 찾고, 기관 담당자는 공고마다 맞는 기업을 찾아 참여를 권하는 서비스 PoC.

```
backend/         FastAPI API (backend/README.md)
frontend/        Vite + React 화면. 기업 화면(로그인 없음) + 기관 담당자 화면 (frontend/README.md)
db/migrations/   PostgreSQL 16 + pgvector 스키마 (파일별 단일 트랜잭션)
db/tests/        SQL 스모크 테스트 (샘플 데이터 → 흐름 확인 → ROLLBACK)
seeds/           base.sql (담당자 계정·사업), navigator_*.sql (가상 기업·공고, navigator_consult.sql·navigator_route.sql 은 상담용 가상 데이터), navigator_eval/ (검증 데이터)
scripts/         migrate.sh (체크섬 검증), smoke_test.sh (curl API 스모크), mac_autostart.sh
docs/            navigator.md (API·판정 규칙), navigator_ux.md (화면 표기), navigator_eval.md (검증 결과)
```

## 로컬 실행

```bash
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/navigator
./scripts/migrate.sh                                                         # 1. 스키마
for f in base navigator_companies navigator_announcements navigator_past_announcements navigator_consult navigator_route; do
  psql "$DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -f seeds/$f.sql            # 2. 시드 (여러 번 실행해도 안전)
done
(cd backend && uvicorn app.main:app --port 8000) &                            # 3. API (기본 EMBEDDER=hash)
BASE_URL=http://localhost:8000 ./scripts/smoke_test.sh                       # 4. API 스모크 (curl, jq 필요)
```

시드 사용자(`X-User-Id`): 1 기관 담당자(STAFF) · 2 역할 없음(권한 거부 확인용) · 3 지원사업 소관부서(PROGRAM_OWNER) · 4 AX 주관부서(AX_ADMIN).

## 한 주소로 실행 (맥)

```bash
./scripts/mac_autostart.sh   # 화면 빌드 + 로그인 시 자동 실행 등록. 이후 http://127.0.0.1:8000/navigator
```

API 는 `/api/*`, 나머지는 빌드된 화면 (`backend/app/site.py`). 자동 실행 없이 한 번만: `cd frontend && npm run build` 후 `cd backend && uvicorn app.site:site --port 8000`.


## 시연 주소

링크 하나로 보여 줄 때: `docs/demo_link.md` (Render 무료 호스팅 또는 맥 + 임시 주소, 가상 데이터·비밀번호·메일 끔).
