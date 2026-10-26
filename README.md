# relay-ax-db

국방 R&D 성과연계·이어달리기 AX PoC 의 PostgreSQL 16 + pgvector 스키마 (프레임워크 중립 순수 SQL).

```
db/migrations/   0001~0015 순번 마이그레이션 (파일별 단일 트랜잭션)
db/optional/     IVFFlat 인덱스 대안
db/tests/        스모크 테스트 (샘플 데이터 → 전체 흐름 검증 → ROLLBACK)
scripts/         migrate.sh (psql 기반 실행기, 체크섬 검증)
docs/ERD.md      ERD·설계 설명·가정·요구사항 매핑
backend/         FastAPI 백엔드 (매칭·추천 엔진, HITL 검토 API) — backend/README.md
```

```bash
DATABASE_URL=postgres://user:pass@host:5432/relay_ax ./scripts/migrate.sh
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/tests/smoke_test.sql
```

설계 가정(임베딩 1024차원, cosine, HNSW 등)은 `docs/ERD.md` 1장 참조.
