#!/usr/bin/env bash
# 시연 주소 시작: 스키마 → 가상 데이터(기업 3곳·공고 5건 등, 여러 번 실행해도 안전) → 서버
set -euo pipefail
cd "$(dirname "$0")/.."
: "${DATABASE_URL:?DATABASE_URL 을 설정하세요}"
./scripts/migrate.sh
for f in base navigator_companies navigator_announcements navigator_past_announcements; do
  psql "$DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -o /dev/null -f "seeds/$f.sql"
done
(cd backend && python -m app.reembed)
cd backend
exec uvicorn app.site:site --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
