#!/usr/bin/env bash
# 맥에서 화면을 빌드하고, 로그인할 때마다 API+화면(127.0.0.1:8000)이 자동으로 뜨게 등록한다.
# 이후에는 브라우저에서 http://127.0.0.1:8000/navigator 만 열면 된다. 코드를 받은 뒤 다시 실행하면 재빌드·재시작.
# 해제: launchctl bootout gui/$(id -u)/kr.navigator; rm ~/Library/LaunchAgents/kr.navigator.plist
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL=kr.navigator
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/navigator-logs"; mkdir -p "$LOG"

(cd "$ROOT/frontend" && npm install --silent && npm run build)
(cd "$ROOT/backend" && .venv/bin/pip install -q -e .)

cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>WorkingDirectory</key><string>$ROOT/backend</string>
  <key>ProgramArguments</key><array>
    <string>$ROOT/backend/.venv/bin/uvicorn</string><string>app.site:site</string>
    <string>--host</string><string>127.0.0.1</string><string>--port</string><string>8000</string>
  </array>
  <key>EnvironmentVariables</key><dict><key>NAVIGATOR_DEV_EXPOSE_LINK</key><string>true</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG/api.log</string>
  <key>StandardErrorPath</key><string>$LOG/api.log</string>
</dict></plist>
PL
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
# bootout 은 바로 끝나지 않는다. 내려가기 전에 bootstrap 하면 "Bootstrap failed: 5"
for _ in $(seq 20); do launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || break; sleep 0.5; done
lsof -tiTCP:8000 -sTCP:LISTEN | xargs kill 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST" || { sleep 3; launchctl bootstrap "gui/$(id -u)" "$PLIST"; }
until curl -sf 127.0.0.1:8000/api/health >/dev/null; do sleep 2; done
echo "기업 화면:   http://127.0.0.1:8000/navigator"
echo "담당자 화면: http://127.0.0.1:8000/login (기관 담당자) -> /staff/navigator"
