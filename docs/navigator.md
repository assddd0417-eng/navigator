# Navigator (기업 대상 서비스)

- [1단계: 기업 프로필 기본](#1단계-기업-프로필-기본)
- [2단계: 공고](#2단계-공고)

## 1단계: 기업 프로필 기본

기업 프로필 ↔ 열린 공고를 짝짓는 Navigator 의 첫 단계. 기존 이어달리기 기능은 그대로 두고 옆에 더한다.
전체 설계: "Navigator 기업 대상 서비스 설계 (1단계)" (2026-11-09). 단계마다 PR 하나.

### 이번 단계에서 만든 것

| 구분 | 내용 |
|------|------|
| 마이그레이션 0019 | `company_profile` 칸 추가(대표자명, 개업일, 설립일, 직원 수, 매출, 지역, 휴·폐업, 진위확인 결과, 등록 이메일), `company_patent`, `company_certification`, `code_certification_type`, `company_credit_rating`, `company_rnd_history`, `company_access_link` |
| 마이그레이션 0020 | `external_source`(출처 7곳 목록), `external_fetch_job`, `external_raw_record`, `company_field_source`, 뷰 `v_company_field_compare` |
| API (로그인 없음) | `backend/app/routers/navigator.py` — 아래 표 |
| 국세청 진위확인 | 연결 부품 `backend/app/services/external/nts.py`. `SOURCE_NTS_BIZ=mock`(기본)은 가상 등록부(`fixtures/nts_mock.json`)로 응답, `live` 는 6단계에서 연결 |
| 관리 링크 | `backend/app/services/access_link.py`. 비밀값 256비트, DB 에는 SHA-256 해시만, 기본 30일 만료, 다시 요청하면 이전 링크 폐기 |
| 이메일 | `backend/app/services/mailer.py`. `MAILER=mock`: 보내지 않고 기록만 (실제 발송은 5단계) |
| 가상 기업 3곳 | `seeds/navigator_companies.sql` (재실행 안전) |

기존 테이블은 지우거나 바꾸지 않았다 (`company_profile` 에 칸만 추가, 감사 트리거 추가).
사업자번호는 새 칸을 만들지 않고 기존 `organization.business_reg_no`(UNIQUE)를 쓴다. Navigator 는 하이픈 없는 숫자 10자리로 저장·조회한다.

### API

| 메서드·경로 | 누가 | 하는 일 |
|-------------|------|---------|
| `POST /navigator/companies` | 누구나 | 등록. 사업자번호 형식(검증번호) 검사 → 국세청 진위확인 → 저장 → 등록 이메일로 관리 링크 |
| `GET /navigator/companies/{사업자번호}` | 누구나 | 공개 정보만: 상호, 확인됨/미확인, 휴·폐업, 특허 |
| `POST /navigator/companies/{사업자번호}/access-link` | 누구나 | 관리 링크 다시 받기. **처음 등록한 이메일로만** 보냄 |
| `GET /navigator/manage/profile` | 관리 링크 (`X-Manage-Token`) | 내 프로필 전체: 신용등급, 매출·직원 수, 인증, R&D 이력, 칸별 출처 |
| `PATCH /navigator/manage/profile` | 관리 링크 | 고치기. 보낸 칸만 바뀌고 '자가입력·미확인'으로 기록. 목록(특허 등)을 보내면 자가입력 행만 통째로 교체 |

### 등록 규칙

- 진위확인 **확인됨**(사업자번호·대표자명·개업일 일치): 저장, 화면에 "확인됨".
- **불일치**(등록부에 있으나 대표자명·개업일이 다름): 저장하지 않음 (422). 남의 사업자번호로 거짓 프로필을 만드는 것을 막는다. 수집 기록은 남는다.
- **확인 불가**(등록부에 없음, 연결 안 됨): 저장하되 "미확인".
- 사업자번호당 프로필은 하나. 이미 등록돼 있으면 409, 관리 링크 다시 받기로 안내.
- 기관 DB 에 이미 있는 기업(이메일 없는 기업)은 진위확인 **확인됨**일 때만 이어서 등록할 수 있다.
- 이메일은 필수(관리 링크·알림용).
- 로그인 없는 API 는 같은 곳에서 1분에 `NAVIGATOR_RATE_LIMIT_PER_MINUTE`(기본 60)회까지.

### 값의 출처 기록

모든 값은 `company_field_source` 에 출처(SELF 자가입력 / EXTERNAL 외부 / INTERNAL 내부 / STAFF 담당자)와 확인 여부를 남긴다.
자가입력과 외부값이 다르면 둘 다 보관하고, `v_company_field_compare` 가 확인된 외부값을 앞에 두고 `differs = true` 로 차이를 표시한다.
특허·인증·신용등급·R&D 이력 행은 각자 `origin`, `verified_at` 칸을 가진다. R&D 이력의 과제번호가 내부 과제(`project.project_no`)와 같으면 자동으로 연결한다.

### 가상 기업 3곳

모든 사업자번호는 가상(999- 로 시작)이다.

| ID | 사업자번호 | 기업 | 분야 | 상태 |
|----|-----------|------|------|------|
| 101 | 999-81-00015 | (가상)한빛전자통신 | 전술 데이터링크·통신, 대전, SME | 확인됨. R&D 이력 하나가 내부 과제 PRJ-2022-001 과 연결 |
| 102 | 999-82-00026 | (가상)누리복합소재 | 방탄·항공 복합소재, 경남, 중견 | 확인됨, 방산업체 지정. 매출 자가입력 1,240억 vs DART(목업) 1,198억 → 차이 표시 |
| 103 | 999-83-00038 | (가상)새봄비전AI | EO/IR 영상 AI, 경기, 스타트업 | 미확인, 신용등급 자가입력, R&D 이력 없음 (3단계 '정보부족' 예시) |

관리 링크는 비밀값이라 시드에 넣지 않는다. `POST /navigator/companies/999-81-00015/access-link` 로 받는다.

### 설정 (환경변수)

| 이름 | 기본 | 설명 |
|------|------|------|
| `SOURCE_NTS_BIZ` | `mock` | 국세청 연결 부품. `live` 는 6단계에서 연결 (지금은 '미확인'으로 처리) |
| `MAILER` | `mock` | 메일 발송. mock 은 기록만 |
| `NAVIGATOR_PUBLIC_BASE_URL` | `http://localhost:5173` | 관리 링크 주소 앞부분 (기업 화면) |
| `NAVIGATOR_LINK_TTL_DAYS` | `30` | 관리 링크 유효 기간 |
| `NAVIGATOR_RATE_LIMIT_PER_MINUTE` | `60` | 로그인 없는 API 조회 제한 |
| `NAVIGATOR_DEV_EXPOSE_LINK` | `false` | `true` 면 응답에 관리 링크를 실어 줌. 로컬 확인용, 운영 금지 |

### 로컬에서 확인

```bash
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/relay_ax
./scripts/migrate.sh
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f seeds/init_test_data.sql
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f seeds/navigator_companies.sql
(cd backend && NAVIGATOR_DEV_EXPOSE_LINK=true uvicorn app.main:app --port 8000) &

# 1) 사업자번호로 공개 조회
curl -s localhost:8000/navigator/companies/999-81-00015 | jq
# 2) 새 기업 등록 (목업 등록부에 있는 가상 번호 → 확인됨)
curl -s -X POST localhost:8000/navigator/companies -H 'Content-Type: application/json' -d '{
  "business_reg_no":"999-84-00049","company_name":"(가상)길동정밀","representative_name":"홍길동",
  "opened_on":"2019-03-01","email":"me@example.com","employee_count":42,"region":"충남"}' | jq
# 3) 응답의 dev_management_link 에서 #t= 뒤 값을 꺼내 내 프로필 보기
curl -s localhost:8000/navigator/manage/profile -H "X-Manage-Token: <비밀값>" | jq
```

### 다음 단계로 미룬 것

- 기관 담당자용 기업 조회 화면·API (4단계, 기존 로그인)
- 증빙 PDF 업로드 연결 (`evidence_document_id` 칸만 마련, 2단계 PDF 기능 재사용 때 연결)
- 성과카드 참여기업(`card_company`) → R&D 이력 자동 반영 (3단계 매칭 때)
- 국세청 실제 연결·주기 수집 (6단계), 실제 메일 발송 (5단계)
- 조회 제한은 프로세스 메모리 기준 (서버를 여러 대로 늘리면 공유 저장소로)

## 2단계: 공고

기업과 비교할 공고를 넣는다. 등록·수정은 기관 담당자(로그인, `PLANNER` 또는 `ADMIN`), 조회는 로그인 없이도 된다.
공고 범위는 국방 R&D 공고부터 (`domain = DEFENSE_RND` 기본, 일반 지원사업·입찰은 칸만 마련).

### 만든 것

| 구분 | 내용 |
|------|------|
| 마이그레이션 0021 | `announcement`(기존 `program` 사업트랙과 연결, 원문은 기존 `source_document`), `announcement_requirement`(자격요건 한 줄씩), `announcement_tech_need`, 코드표 `code_requirement_type`(13종), `code_credit_grade`(AAA~D 서열), 뷰 `v_announcement`(접수 상태 계산) |
| API | `backend/app/routers/announcements.py` — 아래 표 |
| 자격요건 형식 | `backend/app/schemas/announcements.py` 의 `RULE_MODELS`. 종류마다 `rule` 형식을 검사·정규화한다. 3단계 판정기가 같은 형식을 읽는다 |
| PDF 업로드 | 기존 문서 기능(`parse_file`, `store_document`)을 그대로 써서 공고문을 쪽 단위 청크로 저장. 자격요건마다 근거 청크를 연결할 수 있다 |
| 가상 공고 5건 | `seeds/navigator_announcements.sql` (재실행 안전) |

기존 코드 변경은 `routers/documents.py` 에서 문서 저장 부분을 함수(`store_document`, `parse_file`)로 꺼낸 것뿐이다 (동작 같음).

### API

| 메서드·경로 | 누가 | 하는 일 |
|-------------|------|---------|
| `POST /navigator/announcements` | 담당자 | 직접 입력 (자격요건·요구기술 함께). 요건 하나라도 틀리면 통째로 저장 안 함 |
| `POST /navigator/announcements/upload` | 담당자 | 공고문 PDF → 원문 청크 저장 → **작성중(DRAFT)** 공고 |
| `GET /navigator/announcements` | 누구나 | 목록. `receipt_state=UPCOMING\|OPEN\|CLOSED`, `q`(제목) 로 거르기 |
| `GET /navigator/announcements/{id}` | 누구나 | 상세: 자격요건(필수/우대, 원문 인용·쪽), 요구기술, 원문 문서 |
| `GET /navigator/announcements/{id}/chunks?q=` | 누구나 | 공고문 원문 줄 (근거로 고를 chunk_id) |
| `PATCH /navigator/announcements/{id}` | 담당자 | 수정. `status=PUBLISHED` 로 공개, `CANCELLED` 로 취소 |
| `POST /navigator/announcements/{id}/requirements` | 담당자 | 자격요건 한 줄 추가 (`evidence.chunk_id` 로 원문 근거 연결) |
| `PATCH`·`DELETE .../requirements/{rid}` | 담당자 | 한 줄 고치기·지우기 |
| `POST /navigator/announcements/{id}/tech-needs`, `DELETE .../tech-needs/{tid}` | 담당자 | 요구 기술 |

로그인 없이 보면 공개(PUBLISHED) 공고만 보인다. 접수 상태는 날짜로 계산한다: 접수전(UPCOMING) / 접수중(OPEN) / 마감(CLOSED).

### 자격요건 종류와 rule 형식

| 코드 | 이름 | rule 예 |
|------|------|---------|
| `COMPANY_SIZE` | 기업규모 | `{"allowed":["SME","STARTUP","VENTURE"]}` |
| `BUSINESS_AGE` | 업력 | `{"min_years":3,"max_years":7}` (기준일: 접수 마감일) |
| `REQUIRED_CERT` | 필수인증 | `{"any_of":["RND_LAB","RND_DEPT"]}` (인증 코드표에 있는 코드만) |
| `MIN_CREDIT_GRADE` | 최저신용등급 | `{"min_grade":"BB-"}` (신용등급 코드표에 있는 등급만) |
| `REGION` | 지역 | `{"allowed":["대전","충남"]}` |
| `TRL` | 기술성숙도 | `{"min":4,"max":7}` (기업 프로필에 없음 → 3단계 보완질문) |
| `EMPLOYEE_COUNT` | 직원 수 | `{"min":5,"max":300}` |
| `REVENUE` | 매출 | `{"min_krw":0,"max_krw":150000000000}` |
| `BUSINESS_STATUS` | 휴·폐업 | `{"allowed":["ACTIVE"]}` |
| `DEFENSE_COMPANY` | 방산업체 지정 | `{"required":true}` |
| `RND_EXPERIENCE` | R&D 수행 경험 | `{"min_count":1,"role":"LEAD","within_years":5}` |
| `PATENT` | 특허 보유 | `{"min_count":1,"status":"REGISTERED","ipc_prefixes":["H04"]}` |
| `OTHER` | 기타 | `{}` — 문장(description)이 본체. 3단계에서 항상 확인 필요 |

### 가상 공고 5건과 의도한 판정

가상 기업 3곳과 섞어 3단계 판정이 세 가지(적합/정보부족/부적격)로 갈리도록 짰다. 판정은 3단계에서 실제로 확인한다.

| ID | 공고 | 접수 (2026-11-09 기준) | 의도한 판정 |
|----|------|------------------------|-------------|
| 101 | 전술통신 부품국산화 개발지원 | 접수중 | 한빛 적합 · 누리 부적격(중견) · 새봄 부적격(연구소 없음) |
| 102 | 경량 방탄 복합소재 핵심기술 | 접수중 | 누리 적합 · 한빛·새봄 부적격(품질인증 없음) |
| 103 | AI 영상 표적탐지 신속시범 | 접수중 | 새봄 정보부족(TRL 모름) · 한빛 부적격(업력) · 누리 부적격(규모) |
| 104 | 강원 접경지역 국방벤처 육성 | 접수전 | 모두 부적격 (일부러 안 맞는 공고) |
| 105 | 2026 하반기 국방 R&D 과제 공모 | 마감 | 한빛·누리 정보부족(보안측정 '기타' 요건) · 새봄 부적격(주관 이력 없음) |

### 로컬에서 확인

```bash
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f seeds/navigator_announcements.sql
curl -s localhost:8000/navigator/announcements | jq '.[] | {id, title, receipt_state_label, mandatory_count}'
curl -s localhost:8000/navigator/announcements/101 | jq '.requirements[] | {req_type_name, mandatory_label, rule, source_quote}'
# 공고문 PDF 올리기 (담당자) → 작성중 공고
curl -s -X POST localhost:8000/navigator/announcements/upload -H 'X-User-Id: 1' \
  -F file=@공고문.pdf -F announcement_no=MY-001 -F agency_name='(가상)기관' -F receipt_end=2026-12-31 | jq
```

### 다음 단계로 미룬 것

- 공고문에서 자격요건 자동 추출(AI) — `origin = AI_EXTRACTED` 칸만 마련, 지금은 담당자가 원문을 보고 한 줄씩 입력
- 외부 공고 수집(기업마당·나라장터·방사청) — 6단계, `source_kind = EXTERNAL`
- 공고 임베딩·매칭·판정 — 3단계
