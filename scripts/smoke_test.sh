#!/usr/bin/env bash
# API 스모크 테스트: 실행 중인 백엔드에 curl 로 주요 흐름을 한 번 돌려 본다.
#   ① /health  ② 기업 정보  ③ 공고  ④ 공고문 PDF  ⑤ 매칭·판정  ⑥ 알림  ⑦ 외부 수집  ⑧ 공고 등록·조건 확인  ⑨ 기업 상담
#
# 사용법:
#   BASE_URL=http://localhost:8000 ./scripts/smoke_test.sh
#
# 전제: 마이그레이션 + seeds/base.sql + seeds/navigator_companies.sql + seeds/navigator_announcements.sql
#       (+ navigator_past_announcements.sql, navigator_consult.sql) 적용, 서버 실행 중 (기본 EMBEDDER=hash).
# 필요 도구: curl, jq   (PDF 픽스처: scripts/fixtures/*.pdf)
# 재실행 안전: 공고번호에 실행 태그를 붙여 매번 새 데이터로 돈다.
# 종료 코드: 모두 통과 0, 하나라도 실패 1.
set -uo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
BASE_URL="${BASE_URL%/}"
RUN_TAG="${RUN_TAG:-$(date +%Y%m%d%H%M%S)-$$}"
VERBOSE="${VERBOSE:-0}"          # 1 이면 실패하지 않은 응답 본문도 출력

# 시드 사용자 (seeds/base.sql)
STAFF=1 VIEWER=2

for bin in curl jq; do
    command -v "$bin" >/dev/null || { echo "필요 도구가 없습니다: $bin" >&2; exit 2; }
done

if [[ -t 1 ]]; then G=$'\e[32m' R=$'\e[31m' Y=$'\e[33m' B=$'\e[1m' N=$'\e[0m'; else G= R= Y= B= N=; fi

PASS_COUNT=0 FAIL_COUNT=0 SKIP_COUNT=0
BODY_FILE="$(mktemp)"
trap 'rm -f "$BODY_FILE"' EXIT
BODY="" STATUS=""

section() { printf '\n%s== %s ==%s\n' "$B" "$1" "$N"; }
pass()    { PASS_COUNT=$((PASS_COUNT + 1)); printf '  %sPASS%s %s\n' "$G" "$N" "$1"; }
fail()    { FAIL_COUNT=$((FAIL_COUNT + 1)); printf '  %sFAIL%s %s\n' "$R" "$N" "$1"; }
skip()    { SKIP_COUNT=$((SKIP_COUNT + 1)); printf '  %sSKIP%s %s\n' "$Y" "$N" "$1"; }
show_body() { printf '       %s\n' "$(printf '%s' "$BODY" | head -c 800)"; }

summary() {
    printf '\n%s결과%s: PASS %d · FAIL %d · SKIP %d  (BASE_URL=%s, RUN_TAG=%s)\n' \
        "$B" "$N" "$PASS_COUNT" "$FAIL_COUNT" "$SKIP_COUNT" "$BASE_URL" "$RUN_TAG"
    [[ $FAIL_COUNT -eq 0 ]]
}

# 뒤 단계가 이 결과에 의존할 때: 실패하면 요약 후 중단
abort() { printf '  %s중단%s: %s\n' "$R" "$N" "$1"; summary; exit 1; }

# api <설명> <기대 상태코드> <메서드> <경로> <사용자ID|-> [JSON 본문]
#   사용자ID 가 '-' 이면 X-User-Id 헤더를 보내지 않는다. 결과는 $STATUS, $BODY 에 남는다.
api() {
    local desc=$1 expect=$2 method=$3 path=$4 user=$5 data=${6:-}
    local args=(-sS -o "$BODY_FILE" -w '%{http_code}' -X "$method" "$BASE_URL$path"
                -H 'Accept: application/json' -H "X-Request-Id: smoke-$RUN_TAG")
    [[ "$user" != "-" ]] && args+=(-H "X-User-Id: $user")
    [[ -n "$data" ]] && args+=(-H 'Content-Type: application/json' --data "$data")
    STATUS=$(curl "${args[@]}" 2>/dev/null) || STATUS="000"
    BODY=$(cat "$BODY_FILE" 2>/dev/null || true)
    local who; [[ "$user" == "-" ]] && who="헤더 없음" || who="X-User-Id: $user"
    if [[ "$STATUS" == "$expect" ]]; then
        pass "$desc → $method $path [$who] HTTP $STATUS"
        [[ "$VERBOSE" == 1 ]] && show_body
        return 0
    fi
    fail "$desc → $method $path [$who] 기대 $expect, 실제 HTTP $STATUS"
    show_body
    return 1
}

# upload <설명> <기대 상태코드> <경로> <사용자ID> <파일경로> [-F 필드...]  : multipart 파일 업로드
upload() {
    local desc=$1 expect=$2 path=$3 user=$4 file=$5; shift 5
    local args=(-sS -o "$BODY_FILE" -w '%{http_code}' -X POST "$BASE_URL$path"
                -H 'Accept: application/json' -H "X-Request-Id: smoke-$RUN_TAG" -H "X-User-Id: $user"
                -F "file=@$file")
    for field in "$@"; do args+=(--form-string "$field"); done  # 값이 ( 로 시작하면 -F 는 다중 파트로 읽음
    STATUS=$(curl "${args[@]}" 2>/dev/null) || STATUS="000"
    BODY=$(cat "$BODY_FILE" 2>/dev/null || true)
    if [[ "$STATUS" == "$expect" ]]; then
        pass "$desc → POST $path [$(basename "$file"), X-User-Id: $user] HTTP $STATUS"
        [[ "$VERBOSE" == 1 ]] && show_body
        return 0
    fi
    fail "$desc → POST $path [$(basename "$file"), X-User-Id: $user] 기대 $expect, 실제 HTTP $STATUS"
    show_body
    return 1
}

# check <설명> <jq 필터(참/거짓)> [jq 인자...]  : 직전 응답 본문 검증
check() {
    local desc=$1 filter=$2; shift 2
    if printf '%s' "$BODY" | jq -e "$@" "$filter" >/dev/null 2>&1; then
        pass "$desc"; return 0
    fi
    fail "$desc  (jq: $filter)"; show_body; return 1
}

# pick <jq 필터> [jq 인자...]  : 직전 응답에서 값 하나 추출 (없으면 빈 문자열)
pick() { local filter=$1; shift; printf '%s' "$BODY" | jq -r "$@" "$filter // empty" 2>/dev/null; }

printf '%sAPI 스모크 테스트%s  BASE_URL=%s  RUN_TAG=%s\n' "$B" "$N" "$BASE_URL" "$RUN_TAG"

# -----------------------------------------------------------------------------
section "① 헬스체크"
api "헬스체크" 200 GET /health - || abort "서버에 연결할 수 없거나 비정상입니다 ($BASE_URL)"
# 기대 스키마 버전 = db/migrations 의 마지막 번호 (마이그레이션 추가 시 스크립트 수정 불필요)
LATEST_SCHEMA=$(basename "$(ls "$(dirname "$0")"/../db/migrations/[0-9][0-9][0-9][0-9]_*.sql | sort | tail -1)" | cut -c1-4)
check "status=ok, 스키마 $LATEST_SCHEMA 적용, pgvector 설치" \
    '.status == "ok" and .schema_version == $v and (.pgvector | type) == "string"' --arg v "$LATEST_SCHEMA"
api "인증 헤더 없으면 401" 401 GET /me -
api "시드 사용자 확인 (STAFF=$STAFF)" 200 GET /me "$STAFF" \
    || abort "시드 사용자가 없습니다. seeds/base.sql 을 먼저 적용하세요"
check "기관 담당자 역할" '.roles == ["STAFF"]'

# -----------------------------------------------------------------------------
section "② 기업 정보 (로그인 없음, seeds/navigator_companies.sql 필요)"
api "가상 기업 공개 조회 (사업자번호)" 200 GET /navigator/companies/999-81-00015 -
check "확인됨 · 특허 공개 · 신용등급 숨김" \
    '.biz_verify_label == "확인됨" and (.patents | length) >= 1 and (has("credit_ratings") | not)'
api "미확인 가상 기업 공개 조회" 200 GET /navigator/companies/9998300038 -
check "미확인 표시" '.biz_verify_label == "미확인"'
api "관리 링크 없이 내 프로필" 401 GET /navigator/manage/profile -
api "관리 링크 없이 증빙 올리기" 401 POST /navigator/manage/evidence -
api "사업자번호 형식 오류" 422 POST /navigator/companies - \
    '{"business_reg_no":"999-81-00016","company_name":"x","representative_name":"x","opened_on":"2020-01-01","email":"a@b.co"}'
api "이미 등록된 사업자번호 재등록 거부" 409 POST /navigator/companies - \
    '{"business_reg_no":"999-81-00015","company_name":"x","representative_name":"김한빛","opened_on":"2012-03-15","email":"a@b.co"}'

# -----------------------------------------------------------------------------
section "③ 공고 (seeds/navigator_announcements.sql 필요)"
api "공고 목록 (로그인 없음)" 200 GET "/navigator/announcements?q=%EA%B0%80%EC%83%81" -
check "가상 공고 5건, 105 는 마감" \
    '([.[] | select(.announcement_no | test("^NAV-2026-10[1-5]$"))] | length) == 5
     and any(.[]; .announcement_no == "NAV-2026-105" and .receipt_state == "CLOSED")'
api "공고 상세 (자격요건·요구기술)" 200 GET /navigator/announcements/101 -
check "자격요건 8줄 (필수 5·우대 3) · 요구기술 2" \
    '(.requirements | length) == 8 and ([.requirements[] | select(.is_mandatory)] | length) == 5
     and (.tech_needs | length) == 2'
api "로그인 없이 공고 등록 거부" 401 POST /navigator/announcements - '{"announcement_no":"x","title":"x","agency_name":"x"}'
api "공고 직접 입력 (STAFF)" 201 POST /navigator/announcements "$STAFF" \
    "$(jq -n --arg no "SMOKE-$RUN_TAG" '{announcement_no: $no, title: "스모크 공고", agency_name: "(가상)기관",
        requirements: [{req_type_code: "MIN_CREDIT_GRADE", rule: {min_grade: "BB-"}, description: "BB- 이상"}]}')"
api "잘못된 규칙 거부" 422 POST /navigator/announcements "$STAFF" \
    "$(jq -n --arg no "SMOKE-BAD-$RUN_TAG" '{announcement_no: $no, title: "x", agency_name: "x",
        requirements: [{req_type_code: "MIN_CREDIT_GRADE", rule: {min_grade: "Z"}, description: "x"}]}')"

# -----------------------------------------------------------------------------
section "④ 공고문 PDF 올리기"
FIX="$(dirname "$0")/fixtures"
PDF_FIELDS=("announcement_no=PDF-$RUN_TAG" "agency_name=(가상)기관")
upload "열람자는 거부" 403 /navigator/announcements/upload "$VIEWER" "$FIX/report_ko.pdf" "${PDF_FIELDS[@]}"
upload "공고문 PDF 등록 (제목은 파일 이름)" 201 /navigator/announcements/upload "$STAFF" "$FIX/report_ko.pdf" "${PDF_FIELDS[@]}"
check "작성 중 공고, 원문 청크 저장" '.id > 0 and .chunk_count > 0'
upload "스캔본(글자 없음) 거부" 422 /navigator/announcements/upload "$STAFF" "$FIX/scanned.pdf" "announcement_no=PDF2-$RUN_TAG" "agency_name=(가상)기관"
upload "암호 걸린 PDF 거부" 422 /navigator/announcements/upload "$STAFF" "$FIX/encrypted.pdf" "announcement_no=PDF3-$RUN_TAG" "agency_name=(가상)기관"

# -----------------------------------------------------------------------------
section "⑤ 매칭과 판정 (가상 기업 3곳 × 공고 5건)"
api "매칭은 담당자만 (VIEWER)" 403 POST /navigator/matching/announcements/101 "$VIEWER"
api "공고 101 → 기업 (STAFF)" 201 POST /navigator/matching/announcements/101 "$STAFF"
check "한빛 적합 1위 · 누리·새봄 부적격 · 기준별 점수 4개" \
    '.recommendations[0].organization_id == 101 and .recommendations[0].verdict == "ELIGIBLE"
     and (.recommendations[0].scores | length) == 4
     and any(.recommendations[]; .organization_id == 102 and .verdict == "INELIGIBLE")
     and any(.recommendations[]; .organization_id == 103 and .verdict == "INELIGIBLE")'
api "공고 101 참여 권유 대상" 200 GET /navigator/matching/announcements/101/outreach "$STAFF"
check "적합·확인 필요만, 한빛 포함" \
    '.open and all(.companies[]; .verdict != "INELIGIBLE") and any(.companies[]; .organization_id == 101)'
api "권유 메일은 담당자만 (VIEWER)" 403 POST /navigator/matching/announcements/101/outreach "$VIEWER" '{"organization_ids":[101]}'
api "공고 103 → 기업" 201 POST /navigator/matching/announcements/103 "$STAFF"
check "새봄 정보부족 + TRL 보완질문" \
    'any(.recommendations[]; .organization_id == 103 and .verdict == "NEEDS_INFO"
         and any(.questions[]; .question | test("TRL")))'
api "새봄 → 공고 (마감 포함)" 201 POST "/navigator/matching/companies/103?include_closed=true" "$STAFF"
check "103 정보부족 · 101/102/104 부적격" \
    '[.recommendations[] | select(.announcement_id <= 105 and .announcement_id >= 101) | {(.announcement_id|tostring): .verdict}]
     | add | .["103"] == "NEEDS_INFO" and .["101"] == "INELIGIBLE" and .["102"] == "INELIGIBLE" and .["104"] == "INELIGIBLE"'
api "한빛 → 최근 마감 공고 (참여할 수 있었던 사업)" 201 POST "/navigator/matching/companies/101?past=true" "$STAFF"
check "마감 공고만, 다음 회차 표시" \
    'all(.recommendations[]; .receipt_state == "CLOSED")
     and (([.recommendations[] | select(.announcement_id == 106)] | length) == 0
          or any(.recommendations[]; .announcement_id == 106 and .next_round.id == 101))'
api "사업자번호로 추천 공고 (로그인 없음)" 200 GET /navigator/companies/999-82-00026/matches -
check "사업자번호 없음 · 신용등급 요건 결과 가림" \
    'all(.recommendations[]; (has("business_reg_no") | not)
         and all(.checks[]; (.req_type_code != "MIN_CREDIT_GRADE") or (.result == null)))'
api "관리 링크 없이 내 매칭" 401 POST /navigator/manage/matches -

section "⑥ 공고 알림"
api "관리 링크 없이 구독 목록" 401 GET /navigator/manage/subscriptions -
api "잘못된 확인 링크" 404 POST /navigator/subscriptions/confirm - '{"token":"xxxxxxxxxxxxxxxx"}'
api "잘못된 해지 링크" 404 POST /navigator/subscriptions/unsubscribe - '{"token":"xxxxxxxxxxxxxxxx"}'
api "공고 알림 현황은 담당자만 (VIEWER)" 403 GET /navigator/alerts/announcements/101 "$VIEWER"
api "공고 101 알림 현황 (STAFF)" 200 GET /navigator/alerts/announcements/101 "$STAFF"

section "⑦ 외부 수집 (mock)"
api "출처 목록은 담당자만 (VIEWER)" 403 GET /navigator/sources "$VIEWER"
api "출처 목록 (STAFF)" 200 GET /navigator/sources "$STAFF"
api "국세청 휴·폐업 재확인" 200 POST /navigator/sources/NTS_BIZ/run "$STAFF"
api "KIPRIS 특허 (한빛)" 200 POST "/navigator/sources/KIPRIS/run?organization_id=101" "$STAFF"
api "DART 재무 (누리)" 200 POST "/navigator/sources/DART/run?organization_id=102" "$STAFF"
api "기업마당 공고" 200 POST /navigator/sources/BIZINFO/run "$STAFF"
api "국기원 공지사항은 꺼 둠" 404 POST /navigator/sources/KRIT/run "$STAFF"
api "공고는 기업별 수집 안 됨" 422 POST "/navigator/sources/BIZINFO/run?organization_id=101" "$STAFF"
api "연결 안 된 출처" 404 POST /navigator/sources/NICE/run "$STAFF"
api "수집 기록" 200 GET "/navigator/sources/jobs?limit=5" "$STAFF"

section "⑧ 공고 등록·조건 확인"
NOTICE_TEXT='신청자격\n방산 부품을 생산하는 중소기업으로서 기업부설연구소를 보유한 기업\n신청제한\n1. 국세 체납 또는 휴·폐업 중인 기업\n신청기간 : 2026. 11. 16. ~ 11. 27.'
api "공고문 붙여넣기 등록" 201 POST /navigator/announcements/text "$STAFF" \
    "{\"announcement_no\":\"SMK-$RUN_TAG\",\"title\":\"스모크 공고 $RUN_TAG\",\"body_text\":\"$NOTICE_TEXT\"}"
TXT_ANN=$(pick '.id')
if [[ -n "$TXT_ANN" ]]; then
    api "확인 전 목록에 있음" 200 GET "/navigator/announcements?review=PENDING&q=$RUN_TAG" "$STAFF"
    check "작성 중 공고 1건" 'length == 1 and .[0].status == "DRAFT"'
    api "조건 뽑기" 200 POST "/navigator/announcements/$TXT_ANN/extract" "$STAFF"
    check "기업규모·연구소·휴폐업·체납 후보, 접수 마감" \
        '([.requirements[].req_type_code] | contains(["COMPANY_SIZE","REQUIRED_CERT","BUSINESS_STATUS","NO_DISQUALIFICATION"]))
         and .fields.receipt_end == "2026-11-27"'
    REQS=$(printf '%s' "$BODY" | jq -c '[.requirements[] | {req_type_code, rule, is_mandatory, description, source_quote, origin: "AI_EXTRACTED"}]')
    api "조건 확인 저장" 204 PUT "/navigator/announcements/$TXT_ANN/review" "$STAFF" "{\"requirements\":$REQS}"
    api "조건 확인은 담당자만 (VIEWER)" 403 POST "/navigator/announcements/$TXT_ANN/extract" "$VIEWER"
fi

section "⑨ 기업 상담"
api "상담 기업 찾기" 200 GET "/navigator/consult/companies?q=%ED%95%9C%EB%B9%9B" "$STAFF"
check "한빛 검색됨" 'any(.[]; .organization_id == 101)'
api "D-STATE 진단 (한빛)" 201 POST /navigator/consult/companies/101/dstate "$STAFF"
check "6개 영역 · 방산진입 준비기업 · 이력 저장" \
    '(.areas | length) == 6 and .state_type == "DEFENSE_ENTRY" and .diagnosis_id > 0'
api "진단은 담당자만 (VIEWER)" 403 GET /navigator/consult/companies/101/dstate "$VIEWER"
api "자격요건 검토 (한빛 · 컨설팅 공고)" 200 POST /navigator/consult/companies/101/eligibility "$STAFF" \
    '{"concern":"품질체계 구축과 군 수요처 확보"}'
check "접수 공고 판정 · 적합도 등급 · 신청 안내" \
    '(.results | length) >= 2 and (.results[] | select(.announcement_no == "NAV-2026-101") | .fit.grade) != null
     and (.results[] | select(.announcement_no == "NAV-2026-107") | .guide.company_burden) == "컨설팅 비용 25%"'
api "성장경로 연계 기준" 200 GET /navigator/consult/route/rules "$STAFF"
check "3단계 · 연계 기준 8건 이상" '(.stages | length) == 3 and ([.programs[] | select(.stage_code != null)] | length) >= 8'
api "성장경로 (한빛)" 200 POST /navigator/consult/companies/101/route "$STAFF" '{"concern":"품질체계 구축과 군 수요처 확보"}'
check "단기·중기·장기 · 추천 사업 · 안내 문구" \
    '(.steps | length) == 3 and .steps[0].is_current and ([.steps[].programs[]] | length) >= 3 and (.notice | length) > 0'
api "성장경로는 담당자만 (VIEWER)" 403 POST /navigator/consult/companies/101/route "$VIEWER" '{}'
api "상담 요청 목록" 200 GET "/navigator/consult/requests" "$STAFF"
check "가상 상담 요청 있음" 'any(.[]; .organization_id == 101 or .organization_id == 103)'
api "상담 요청 대신 등록 (누리)" 201 POST /navigator/consult/companies/102/requests "$STAFF" \
    '{"concern":"수출 품목 확대 상담","interest":"방산전시회"}'
REQ_ID=$(pick '.id')
api "상담 실행·이력 저장 (누리, 종합)" 201 POST /navigator/consult/companies/102/consultations "$STAFF" \
    "{\"task\":\"C\",\"request_id\":${REQ_ID:-0}}"
check "진단·판정·경로·결과서 초안 7항목" \
    '.status == "DRAFT" and .diagnosis_id > 0 and .route != null and (.report | length) == 7'
CONS_ID=$(pick '.id')
api "결과서 담당자 의견 입력" 200 PUT "/navigator/consult/consultations/${CONS_ID:-0}" "$STAFF" \
    '{"report":{"opinion":"스모크 테스트 의견"},"feedback":"스모크"}'
check "고친 항목 표시" '.edited_sections == ["opinion"]'
api "상담 확정" 200 POST "/navigator/consult/consultations/${CONS_ID:-0}/confirm" "$STAFF" '{"notify":false}'
check "확정 · 기업 화면 공개" '.status == "CONFIRMED" and .shared_at != null'
api "확정 후 수정 불가" 409 PUT "/navigator/consult/consultations/${CONS_ID:-0}" "$STAFF" '{"feedback":"x"}'
api "이력 점검" 200 GET "/navigator/consult/review-log" "$STAFF"
check "고친 상담 포함" 'any(.items[]; .consultation_id == ($id | tonumber))' --arg id "${CONS_ID:-0}"
api "이력 점검은 담당자만 (VIEWER)" 403 GET "/navigator/consult/review-log" "$VIEWER"

summary
