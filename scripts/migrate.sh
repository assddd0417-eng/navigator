#!/usr/bin/env bash
# 순번 SQL 마이그레이션 실행기 (프레임워크 중립, psql 사용)
#   사용법: DATABASE_URL=postgres://user:pass@host:5432/db ./scripts/migrate.sh
#   - db/migrations/NNNN_*.sql 을 번호 순으로, 파일당 단일 트랜잭션으로 적용
#   - ax.schema_migrations 에 버전·체크섬 기록, 이미 적용된 파일은 건너뜀
#   - 적용된 파일 내용이 바뀌면(체크섬 불일치) 중단
# Flyway(V0001__name.sql)·sqitch 등 도입 시 파일만 옮겨 쓰면 된다.
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL 을 설정하세요}"
DIR="$(cd "$(dirname "$0")/.." && pwd)/db/migrations"
PSQL=(psql "$DATABASE_URL" -X -q -v ON_ERROR_STOP=1)

has_table=$("${PSQL[@]}" -Atc "SELECT to_regclass('ax.schema_migrations') IS NOT NULL")

for f in "$DIR"/[0-9][0-9][0-9][0-9]_*.sql; do
    name=$(basename "$f")
    version=${name%%_*}
    sum=$(sha256sum "$f" | cut -d' ' -f1)

    if [[ "$has_table" == "t" ]]; then
        applied=$("${PSQL[@]}" -Atc "SELECT checksum FROM ax.schema_migrations WHERE version = '$version'")
        if [[ -n "$applied" ]]; then
            if [[ "$applied" != "$sum" ]]; then
                echo "오류: $name 이(가) 적용 후 변경되었습니다 (체크섬 불일치)" >&2
                exit 1
            fi
            continue
        fi
    fi

    echo "적용: $name"
    "${PSQL[@]}" --single-transaction \
        -f "$f" \
        -c "INSERT INTO ax.schema_migrations (version, filename, checksum) VALUES ('$version', '$name', '$sum')"
    has_table=t
done
echo "완료"
