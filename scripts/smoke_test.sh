#!/usr/bin/env bash
# =============================================================================
# API 스모크 테스트: 실행 중인 백엔드에 curl 로 전체 흐름을 한 번 돌려 본다.
#
#   ① /health  ② 문서 등록(CURATOR)  ③ 문서 검색  ④ 성과카드 생성·발행
#   ⑤ 수요 등록 → 매칭 → 매칭 런·추천 조회(PLANNER)
#   ⑥ 검토 배정(PLANNER) → 전문가 의견(EXPERT) → 전문가 최종판정 시도 403
#      → 담당부서 최종판정 ADOPT(DEPT_REVIEWER)
#   ⑦ KPI 조회
#
# 사용법:
#   BASE_URL=http://localhost:8000 ./scripts/smoke_test.sh
#
# 전제: 마이그레이션 + seeds/init_test_data.sql 적용, 서버 실행 중 (기본 EMBEDDER=hash).
# 필요 도구: curl, jq
# 재실행 안전: card_no·demand_no·external_ref 에 실행 태그를 붙여 매번 새 데이터로 돈다.
#   같은 DB 에서 수십 번 돌리면 같은 내용의 카드가 쌓여 이번 카드가 상위 K 밖으로 밀리고,
#   그때는 이번 매칭 런의 다른 추천으로 검증하며 2건이 SKIP 된다. 전부 PASS 를 보려면 DB 를 새로 만든다.
# ID 는 하드코딩하지 않고 응답에서 꺼내 쓴다.
# 종료 코드: 모두 통과 0, 하나라도 실패 1.
# =============================================================================
set -uo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
BASE_URL="${BASE_URL%/}"
RUN_TAG="${RUN_TAG:-$(date +%Y%m%d%H%M%S)-$$}"
VERBOSE="${VERBOSE:-0}"          # 1 이면 실패하지 않은 응답 본문도 출력

# 시드 사용자 (seeds/init_test_data.sql)
PLANNER=1 REVIEWER=2 EXPERT=3 CURATOR=4 VIEWER=5
OWNER_DEPT=3                     # 과제 1 소관부서 = 무인미래통신기술팀

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
check "status=ok, 스키마 0015 적용, pgvector 설치" \
    '.status == "ok" and .schema_version == "0015" and (.pgvector | type) == "string"'
api "인증 헤더 없으면 401" 401 GET /cards -
api "시드 사용자 확인 (PLANNER=$PLANNER)" 200 GET /cards "$PLANNER" \
    || abort "시드 사용자가 없습니다. seeds/init_test_data.sql 을 먼저 적용하세요"

# -----------------------------------------------------------------------------
section "② 문서 등록 (CURATOR=$CURATOR)"
CHUNK1_TEXT="광대역 재밍 환경에서 주파수 도약 동기 유지 시간이 목표 10초 대비 6초로 부족하여 후속 연구가 필요함"
CHUNK2_TEXT="시험은 실내 전파차폐실과 야외 시험장에서 수행하였으며 재밍 전력 30dBm 조건을 적용함"
DOC_JSON=$(jq -n --arg tag "$RUN_TAG" --arg c1 "$CHUNK1_TEXT" --arg c2 "$CHUNK2_TEXT" '{
    doc_type_code: "FINAL_REPORT", title: "항재밍 데이터링크 결과보고서", project_id: 1,
    owner_dept_id: 3, external_ref: ("SMOKE-DOC-" + $tag), version_label: "최종", authored_at: "2025-01-15",
    sections: [{key: "s43", section_no: "4.3", heading: "미해결 기술 및 후속 연구 필요사항",
                page_start: 87, page_end: 89}],
    chunks: [
        {content: $c1, section_key: "s43", page_start: 88, location: {paragraph: 2}},
        {content: $c2, section_key: "s43", page_start: 89}
    ]}')
api "권한 없는 사용자(EXPERT)의 문서 등록 거부" 403 POST /documents "$EXPERT" "$DOC_JSON"
api "문서 등록" 201 POST /documents "$CURATOR" "$DOC_JSON" || abort "문서 등록 실패"
check "청크 2개 생성·임베딩" '(.chunk_ids | length) == 2 and .embedded == 2'
DOC_ID=$(pick '.id')
CHUNK_ID=$(pick '.chunk_ids[0]')
CHUNK_IDS=$(pick '.chunk_ids | map(tostring) | join(",")')
[[ -n "$CHUNK_ID" ]] || abort "응답에서 chunk_ids 를 찾지 못했습니다"
printf '       document_id=%s chunk_ids=[%s]\n' "$DOC_ID" "$CHUNK_IDS"

# -----------------------------------------------------------------------------
section "③ 문서 검색"
api "RAG 검색 (CURATOR, 과제 1)" 200 POST /documents/search "$CURATOR" \
    "$(jq -n --arg q "$CHUNK1_TEXT" '{query: $q, k: 5, project_id: 1}')"
check "결과 1건 이상, 1위가 질의한 청크 내용" '(length > 0) and (.[0].content == $q)' --arg q "$CHUNK1_TEXT"
check "출처(조항 4.3·88쪽) 포함" '.[0].section_no == "4.3" and .[0].page_start == 88'
api "열람권 없는 부서(EXPERT)의 검색은 해당 문서 제외" 200 POST /documents/search "$EXPERT" \
    "$(jq -n --arg q "$CHUNK1_TEXT" '{query: $q, k: 5, project_id: 1}')"
check "EXPERT 검색 결과에 과제 1 결과보고서 청크 없음" 'map(select(.content == $q)) | length == 0' --arg q "$CHUNK1_TEXT"

# -----------------------------------------------------------------------------
section "④ 성과카드 생성·발행 (CURATOR=$CURATOR)"
CARD_JSON=$(jq -n --arg tag "$RUN_TAG" --argjson cid "$CHUNK_ID" '{
    card_no: ("SMOKE-AC-" + $tag), project_id: 1, title: "항재밍 주파수 도약 데이터링크",
    core_achievement: "소형 무인기용 주파수 도약 기반 항재밍 데이터링크 시제 개발",
    trl: 5, dev_stage_code: "PROTOTYPE", application_env: "소형 무인기 탑재, 야외 시험장 재밍 환경",
    technologies: [{tech_name: "주파수 도약 항재밍 데이터링크", principle: "고속 주파수 도약과 적응형 채널 선택",
                    is_primary: true, evidence: [{chunk_id: $cid}]}],
    performances: [{metric_name: "동기 유지 시간", target_value: 10, achieved_value: 6, unit: "s",
                    is_achieved: false, evidence: [{chunk_id: $cid}]}],
    open_issues: [{issue_type: "UNRESOLVED_TECH", source: "REPORT",
                   description: "광대역 재밍 환경에서 주파수 도약 동기 유지 시간 부족",
                   evidence: [{chunk_id: $cid, quote: "동기 유지 시간이 목표 10초 대비 6초"}]}],
    weapon_systems: [{id: 1}],
    companies: [{id: 1, relation_type: "TECH_HOLDER", confidence: 0.6}]
}')
api "근거 기반 성과카드 생성" 201 POST /cards "$CURATOR" "$CARD_JSON" || abort "카드 생성 실패"
CARD_ID=$(pick '.id')
printf '       card_id=%s\n' "$CARD_ID"
api "PLANNER 는 발행 불가" 403 POST "/cards/$CARD_ID/publish" "$PLANNER"
api "카드 발행 (매칭 대상)" 204 POST "/cards/$CARD_ID/publish" "$CURATOR" || abort "카드 발행 실패"
api "카드 조회" 200 GET "/cards/$CARD_ID" "$PLANNER"
check "PUBLISHED, 원문 근거 3건(조항 4.3)" \
    '.status == "PUBLISHED" and (.evidence | length) == 3 and .evidence[0].section_no == "4.3"'

# 근거 없는 카드: 이 카드에서 나온 추천은 검토 배정이 DB 가드로 거부되어야 한다 (⑥에서 확인)
NOEV_JSON=$(jq -n --arg tag "$RUN_TAG" '{
    card_no: ("SMOKE-AC-NOEV-" + $tag), project_id: 2, title: "전술 배터리 열관리",
    core_achievement: "상변화물질 기반 배터리 열관리 모듈", trl: 6,
    technologies: [{tech_name: "상변화물질 열관리", is_primary: true}]}')
api "근거 없는 성과카드 생성 (422 가드 확인용)" 201 POST /cards "$CURATOR" "$NOEV_JSON"
NOEV_CARD_ID=$(pick '.id')
[[ -n "$NOEV_CARD_ID" ]] && api "근거 없는 카드 발행" 204 POST "/cards/$NOEV_CARD_ID/publish" "$CURATOR"

# -----------------------------------------------------------------------------
section "⑤ 수요 등록 → 매칭 → 결과 조회 (PLANNER=$PLANNER)"
DEMAND_JSON=$(jq -n --arg tag "$RUN_TAG" '{
    demand_no: ("SMOKE-DM-" + $tag), title: "광대역 재밍 대응 정찰드론 데이터링크",
    tech_need: "광대역 재밍 환경에서 드론 데이터링크 주파수 도약 동기 유지 시간 확보",
    business_purpose: "미래 핵심기술 확보", required_trl_min: 5, required_trl_max: 7,
    target_program_id: 2,
    performance_reqs: [{metric_name: "동기 유지 시간", required_value: 10, unit: "s"}],
    technologies: [{tech_name: "주파수 도약 항재밍 데이터링크"}, {tech_name: "상변화물질 열관리"}],
    weapon_system_ids: [1]}')
api "VIEWER 는 수요 등록 불가" 403 POST /demands "$VIEWER" "$DEMAND_JSON"
api "수요 등록" 201 POST /demands "$PLANNER" "$DEMAND_JSON" || abort "수요 등록 실패"
DEMAND_ID=$(pick '.id')
printf '       demand_id=%s\n' "$DEMAND_ID"

api "매칭 실행" 201 POST "/demands/$DEMAND_ID/match" "$PLANNER" '{"top_k": 20}' || abort "매칭 실패"
RUN_ID=$(pick '.id')
printf '       match_run_id=%s\n' "$RUN_ID"

api "매칭 런 조회" 200 GET "/match-runs/$RUN_ID" "$PLANNER" || abort "매칭 런 조회 실패"
check "SUCCEEDED, 추천 1건 이상" '.status == "SUCCEEDED" and (.recommendations | length) > 0'

# 검토 대상: 이번 카드에서 나온 단일 성과 추천 중 근거가 있는 최상위.
# 같은 DB 에서 여러 번 돌리면 내용이 같은 카드가 쌓여 이번 카드가 상위 K 밖으로 밀릴 수 있으므로,
# 그때는 이번 매칭 런의 다른 근거 있는 추천으로 대신 검증한다 (추천 행은 매칭 런마다 새로 생긴다).
REC_FILTER='[.recommendations[] | select(.linkage_type_code != "CONVERGENCE" and .evidence_count > 0
             and ($c == null or any(.source_cards[]; .card_id == $c)))][0].recommendation_id'
NOEV_FILTER='[.recommendations[] | select(.evidence_count == 0
             and ($c == null or any(.source_cards[]; .card_id == $c)))][0].recommendation_id'
if printf '%s' "$BODY" | jq -e --argjson c "$CARD_ID" 'any(.recommendations[]; any(.source_cards[]; .card_id == $c))' >/dev/null; then
    pass "이번 카드(card_id=$CARD_ID)가 추천 후보에 포함"
    REC_ID=$(pick "$REC_FILTER" --argjson c "$CARD_ID")
else
    skip "이번 카드가 상위 K 밖 (이전 실행 데이터 누적) → 이번 매칭 런의 다른 근거 있는 추천으로 진행"
    REC_ID=$(pick "$REC_FILTER" --argjson c null)
fi
NOEV_REC_ID=$(pick "$NOEV_FILTER" --argjson c "${NOEV_CARD_ID:-0}")
[[ -n "$NOEV_REC_ID" ]] || NOEV_REC_ID=$(pick "$NOEV_FILTER" --argjson c null)
REC_TYPE=$(pick '.recommendations[] | select(.recommendation_id == $r) | .linkage_type_code' --argjson r "${REC_ID:-0}")
[[ -n "$REC_ID" ]] || abort "이번 매칭 런에 근거가 있는 추천이 없습니다"
printf '       recommendation_id=%s (유형 %s)\n' "$REC_ID" "$REC_TYPE"

api "추천 상세 조회" 200 GET "/recommendations/$REC_ID" "$PLANNER"
check "5개 기준 점수와 원문 근거 포함" \
    '([.score_details[].criterion] | sort) == ["ENVIRONMENT","PERFORMANCE","PURPOSE","TECH","TRL"]
     and (.evidence | length) > 0 and .status == "GENERATED"'

# -----------------------------------------------------------------------------
section "⑥ 검토 배정 → 전문가 의견 → 최종판정"
api "EXPERT 는 배정 불가" 403 POST "/recommendations/$REC_ID/assignments" "$EXPERT" \
    "$(jq -n --argjson u "$EXPERT" '{review_role: "EXPERT", assignee_user_id: $u}')"
api "전문가 검토 배정 (PLANNER → EXPERT)" 201 POST "/recommendations/$REC_ID/assignments" "$PLANNER" \
    "$(jq -n --argjson u "$EXPERT" '{review_role: "EXPERT", assignee_user_id: $u}')" || abort "배정 실패"
EXPERT_ASSIGNMENT=$(pick '.id')
api "담당부서 검토 배정 (PLANNER → 부서 $OWNER_DEPT)" 201 POST "/recommendations/$REC_ID/assignments" "$PLANNER" \
    "$(jq -n --argjson d "$OWNER_DEPT" '{review_role: "DEPT_OWNER", assignee_dept_id: $d}')" || abort "배정 실패"
OWNER_ASSIGNMENT=$(pick '.id')
printf '       assignment_id: expert=%s dept_owner=%s\n' "$EXPERT_ASSIGNMENT" "$OWNER_ASSIGNMENT"

if [[ -n "$NOEV_REC_ID" ]]; then
    api "근거 없는 추천의 검토 배정은 422 (DB 가드)" 422 POST "/recommendations/$NOEV_REC_ID/assignments" "$PLANNER" \
        "$(jq -n --argjson u "$EXPERT" '{review_role: "EXPERT", assignee_user_id: $u}')"
else
    skip "근거 없는 카드의 추천이 이번 매칭 결과에 없어 422 확인 생략"
fi

api "EXPERT 검토 대기열에 배정 건 표시" 200 GET /reviews/queue "$EXPERT"
check "대기열에 전문가 배정 포함" 'any(.[]; .assignment_id == $a)' --argjson a "$EXPERT_ASSIGNMENT"

api "전문가 의견 작성 (is_final=false)" 201 POST "/recommendations/$REC_ID/decisions" "$EXPERT" \
    "$(jq -n --argjson a "$EXPERT_ASSIGNMENT" '{decision_code: "ADOPT", assignment_id: $a, opinion: "후속형 연계 적절",
        relevance_rating: 5, evidence_adequacy: 4, dev_needs_accuracy: "CORRECT"}')"

api "EXPERT 의 최종판정 시도는 403" 403 POST "/recommendations/$REC_ID/decisions" "$EXPERT" \
    '{"decision_code": "ADOPT", "is_final": true, "opinion": "전문가가 최종판정 시도"}'
check "403 사유: 최종판정 권한 없음 (DB 트리거)" '.detail | contains("최종판정 권한")'

api "DEPT_REVIEWER 최종판정 ADOPT" 201 POST "/recommendations/$REC_ID/decisions" "$REVIEWER" \
    "$(jq -n --argjson a "$OWNER_ASSIGNMENT" '{decision_code: "ADOPT", is_final: true, assignment_id: $a,
        opinion: "소관부서 검토 결과 채택"}')" || abort "최종판정 실패"

api "판정 후 추천 상태 확인" 200 GET "/recommendations/$REC_ID" "$PLANNER"
check "DECIDED / 최종판정 ADOPT / 배정 모두 SUBMITTED" \
    '.status == "DECIDED" and .final_decision_code == "ADOPT"
     and ([.assignments[].status] | unique) == ["SUBMITTED"]'
check "EXPERT 거부 시도는 판정 이력에 남지 않음 (전문가 의견 1 + 최종 1)" \
    '[.decisions[] | {reviewer_id, is_final}] == [{reviewer_id: $e, is_final: false}, {reviewer_id: $r, is_final: true}]' \
    --argjson e "$EXPERT" --argjson r "$REVIEWER"

api "검토 이력 조회" 200 GET "/recommendations/$REC_ID/history" "$PLANNER"
check "상태 이력 GENERATED → ASSIGNED → IN_REVIEW → DECIDED, 마지막 변경자 DEPT_REVIEWER" \
    '[.status_history[].to_status] == ["GENERATED","ASSIGNED","IN_REVIEW","DECIDED"]
     and .status_history[-1].changed_by == $r' --argjson r "$REVIEWER"
check "감사 로그에 review_decision 기록" 'any(.audit[]; .table_name == "review_decision")'

# -----------------------------------------------------------------------------
section "⑦ KPI 조회"
api "추천 KPI (이번 매칭 런)" 200 GET "/kpi/recommendations?match_run_id=$RUN_ID" "$PLANNER"
check "최종 검토 1건 이상·채택 1건 이상·근거 연결률 > 0" \
    'length == 1 and .[0].finally_reviewed >= 1 and .[0].adopted >= 1
     and ((.[0].evidence_coverage_pct | tonumber) > 0)'
api "평가 KPI" 200 GET /kpi/eval "$PLANNER"
check "배열 응답" 'type == "array"'
api "업무시간 KPI" 200 GET /kpi/work-time "$PLANNER"
check "배열 응답" 'type == "array"'

summary
