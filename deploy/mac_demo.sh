#!/usr/bin/env bash
# 맥에서 시연 주소 열기: 가상 데이터만 든 DB(navigator_demo)로 :8100 에 띄우고 Cloudflare 임시 주소를 붙인다.
# 운영 중인 :8000 (DB navigator)은 건드리지 않는다. 끝내려면 Ctrl+C.
#   SITE_PASSWORD=비밀번호 ./deploy/mac_demo.sh
set -euo pipefail
cd "$(dirname "$0")/.."
: "${SITE_PASSWORD:?SITE_PASSWORD=비밀번호 를 앞에 붙여 실행하세요}"
command -v cloudflared >/dev/null || { echo "cloudflared 가 없습니다: brew install cloudflared" >&2; exit 1; }

export DATABASE_URL="${DEMO_DATABASE_URL:-postgresql://localhost:5432/navigator_demo}"
export SITE_PASSWORD SITE_USER="${SITE_USER:-navigator}" PORT=8100
export EMBEDDER=hash MAILER=mock NAVIGATOR_DEV_EXPOSE_LINK=true
psql "${DATABASE_URL%/*}/postgres" -X -qAtc "SELECT 1 FROM pg_database WHERE datname = 'navigator_demo'" | grep -q 1 \
  || createdb navigator_demo
(cd frontend && npm ci --silent && npm run build >/dev/null)
[ -f backend/.venv/bin/activate ] && source backend/.venv/bin/activate

./deploy/demo_start.sh &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT
until curl -fs localhost:8100/api/health >/dev/null; do sleep 1; done
echo "아이디 $SITE_USER / 비밀번호 $SITE_PASSWORD — 아래 https://...trycloudflare.com 주소를 전달하세요"
cloudflared tunnel --no-autoupdate --url http://localhost:8100
