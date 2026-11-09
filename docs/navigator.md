# Navigator

기업이 사업자번호로 지원 가능한 공고를 찾고, 기관 담당자가 공고별로 적합 기업을 보는 기능.
기업은 로그인 없이 사업자번호 + 관리 링크(등록 이메일로 발송)로 쓰고, 담당자는 기존 로그인을 쓴다.

## 구성

| 구분 | 위치 |
|------|------|
| 마이그레이션 | 0019 기업 프로필(특허·인증·신용등급·R&D 이력·관리 링크), 0020 외부 출처·값 출처, 0021 공고·자격요건, 0022 임베딩·매칭 결과 |
| 기업 API | `backend/app/routers/navigator.py` |
| 공고 API | `backend/app/routers/announcements.py`, 요건 형식 `backend/app/schemas/announcements.py` (`RULE_MODELS`) |
| 매칭 API | `backend/app/routers/navigator_matching.py` |
| 판정 | `backend/app/services/eligibility.py` (DB 없이 테스트 가능한 순수 함수) |
| 매칭 | `backend/app/services/navigator_matching.py`, 벡터 `navigator_embedding.py` |
| 국세청 진위확인 | `backend/app/services/external/nts.py` (mock 은 `fixtures/nts_mock.json`) |
| 관리 링크 / 메일 | `services/access_link.py` / `services/mailer.py` |
| 화면 | `frontend/src/pages/navigator/`, `frontend/src/pages/admin/NavigatorStaffPage.tsx` |
| 테스트 데이터 | `seeds/navigator_companies.sql`, `seeds/navigator_announcements.sql` (재실행 가능) |

기존 테이블은 컬럼 추가만 했다. 사업자번호는 `organization.business_reg_no` 를 숫자 10자리로 쓴다.
기존 코드 변경은 `routers/documents.py` 의 문서 저장 부분을 `store_document`, `parse_file` 로 분리한 것과 `reembed` 에 새 벡터 테이블을 추가한 것뿐이다.

## API

### 기업 (로그인 없음)

| 메서드·경로 | 인증 | 설명 |
|-------------|------|------|
| `POST /navigator/companies` | - | 등록. 사업자번호 검증 → 국세청 진위확인 → 저장 → 관리 링크 발송 |
| `GET /navigator/companies/{brn}` | - | 공개 정보: 상호, 진위확인 결과, 휴·폐업, 특허 |
| `GET /navigator/companies/{brn}/matches` | - | 공개 정보 기준 추천 공고 (아래 '공개 조회' 참고) |
| `POST /navigator/companies/{brn}/access-link` | - | 관리 링크 재발송. 등록 이메일로만 보냄 |
| `GET /navigator/manage/profile` | 관리 링크 | 전체 프로필 (신용등급, 매출, 인증, R&D 이력, 값 출처) |
| `PATCH /navigator/manage/profile` | 관리 링크 | 수정. 보낸 필드만 반영, 출처는 SELF. 목록은 자가입력 행만 교체 |
| `POST /navigator/manage/matches?include_closed=&refresh=` | 관리 링크 | 내 추천 공고. 당일 결과가 있고 이후 변경이 없으면 재사용 |
| `GET /navigator/manage/questions` | 관리 링크 | 보완질문 (부적격 공고 제외, 요건당 1회). `answer_type`: `integer` / `boolean` |
| `POST /navigator/manage/answers` | 관리 링크 | `{"answers":[{"requirement_id":1,"value":7}]}` 저장 후 재판정 결과 반환 |

관리 링크는 `X-Manage-Token` 헤더로 보낸다.

### 공고

| 메서드·경로 | 인증 | 설명 |
|-------------|------|------|
| `GET /navigator/announcements?receipt_state=&q=` | - | 목록. 비로그인은 PUBLISHED 만 |
| `GET /navigator/announcements/{id}` | - | 상세 (자격요건, 원문 인용·쪽, 요구기술) |
| `GET /navigator/announcements/{id}/chunks?q=` | - | 공고문 원문 청크 |
| `POST /navigator/announcements` | 담당자 | 직접 등록. 요건 하나라도 형식 오류면 전체 롤백 |
| `POST /navigator/announcements/upload` | 담당자 | 공고문 PDF → 원문 청크 저장 → DRAFT 공고 |
| `PATCH /navigator/announcements/{id}` | 담당자 | 수정. `status` 로 PUBLISHED / CANCELLED |
| `POST .../requirements`, `PATCH`·`DELETE .../requirements/{rid}` | 담당자 | 자격요건 (`evidence.chunk_id` 로 원문 연결) |
| `POST .../tech-needs`, `DELETE .../tech-needs/{tid}` | 담당자 | 요구기술 |

담당자 = `PLANNER` 또는 `ADMIN`. 접수 상태(UPCOMING / OPEN / CLOSED)는 날짜로 계산한다 (`v_announcement`).

### 매칭 (담당자)

| 메서드·경로 | 설명 |
|-------------|------|
| `POST /navigator/matching/announcements/{id}?verdict=` | 공고 → 기업 매칭 실행 |
| `GET /navigator/matching/announcements/{id}` | 해당 공고의 마지막 실행 결과 (없으면 `run: null`) |
| `POST /navigator/matching/companies/{org_id}?include_closed=` | 기업 → 공고 매칭 |
| `GET /navigator/matching/companies/{org_id}/profile` | 기업 프로필 (이메일 마스킹) |
| `GET /navigator/matching/runs/{run_id}` | 저장된 실행 조회 |

결과 행: `rank`, `verdict`, `total_score`, `scores`, `checks`(요건별 판정·사유·보완질문·원문), `questions`, `evidence`, `rationale`.

## 등록 규칙

- 진위확인 일치: 저장, "확인됨".
- 불일치(등록부에 있으나 대표자명·개업일 다름): 422, 저장 안 함. 수집 기록은 남김.
- 확인 불가(등록부에 없음, 연결 안 됨): 저장, "미확인".
- 사업자번호당 1개. 중복은 409.
- 기관 DB 에 이미 있는 기업(이메일 없음)은 진위확인 일치일 때만 이어서 등록.
- 이메일 필수.
- 비로그인 API 는 IP 당 분당 `NAVIGATOR_RATE_LIMIT_PER_MINUTE` 회 (프로세스 메모리 기준).

관리 링크: 256비트 랜덤, DB 에는 SHA-256 만 저장, 기본 30일, 재발송 시 이전 링크 폐기.
화면에서는 열자마자 주소창에서 지우고 sessionStorage 에만 둔다.

## 값 출처

`company_field_source` 에 출처(SELF / EXTERNAL / INTERNAL / STAFF)와 확인 여부를 남긴다.
자가입력과 외부값이 다르면 둘 다 두고, `v_company_field_compare` 가 확인된 외부값을 우선하고 `differs = true` 로 표시한다.
R&D 이력의 과제번호가 `project.project_no` 와 같으면 내부 과제와 연결한다.

## 자격요건 형식

| 코드 | 이름 | rule 예 |
|------|------|---------|
| `COMPANY_SIZE` | 기업규모 | `{"allowed":["SME","STARTUP","VENTURE"]}` |
| `BUSINESS_AGE` | 업력 | `{"min_years":3,"max_years":7}` |
| `REQUIRED_CERT` | 필수인증 | `{"any_of":["RND_LAB","RND_DEPT"]}` |
| `MIN_CREDIT_GRADE` | 최저신용등급 | `{"min_grade":"BB-"}` |
| `REGION` | 지역 | `{"allowed":["대전","충남"]}` |
| `TRL` | 기술성숙도 | `{"min":4,"max":7}` |
| `EMPLOYEE_COUNT` | 직원 수 | `{"min":5,"max":300}` |
| `REVENUE` | 매출 | `{"min_krw":0,"max_krw":150000000000}` |
| `BUSINESS_STATUS` | 휴·폐업 | `{"allowed":["ACTIVE"]}` |
| `DEFENSE_COMPANY` | 방산업체 지정 | `{"required":true}` |
| `RND_EXPERIENCE` | R&D 수행 경험 | `{"min_count":1,"role":"LEAD","within_years":5}` |
| `PATENT` | 특허 | `{"min_count":1,"status":"REGISTERED","ipc_prefixes":["H04"]}` |
| `OTHER` | 기타 | `{}` (description 으로 판단, 항상 보완질문) |

인증 코드와 신용등급은 코드표(`code_certification_type`, `code_credit_grade`)에 있는 값만 받는다.

## 판정

| 필수 요건 결과 | 판정 |
|----------------|------|
| UNMET 1개 이상 | 부적격 (INELIGIBLE) |
| UNMET 없음, UNKNOWN 있음 | 정보부족 (NEEDS_INFO) |
| 모두 MET | 적합 (ELIGIBLE) |

- 우대 요건은 판정에 쓰지 않고 PREFERENCE 점수에만 반영.
- 기준일은 접수 마감일 (업력, 인증·신용등급 유효기간).
- 창업·벤처는 중소기업에 포함. 벤처 인증이 있으면 벤처, 개업 7년 이하면 창업으로도 본다.
- R&D 이력 = 자가입력 + 성과카드 참여기업(`card_company`)으로 연결된 내부 과제. 이력이 하나도 없으면 UNKNOWN.
- 직원 수·매출은 확인된 외부값 우선.
- TRL, 기타 요건은 보완질문. 답(`eligibility_answer`)이 있으면 그 값으로 판정하고 "자가 신고"로 표시.
- 신용등급 값은 판정 상세·연계이유에 남기지 않고 LLM 에도 보내지 않는다. 연계이유는 템플릿 문장.

### 점수

총점은 가중합, 정렬은 판정 → 총점 순.

| 기준 | 가중치 | 계산 |
|------|--------|------|
| TECH | 0.45 | 요구기술별로 기업 보유기술·특허·R&D·주요사업 중 최대 코사인 유사도, 핵심 요구기술 ×2 가중평균 |
| IPC | 0.15 | 요구기술 IPC 와 기업 특허 IPC 4자리 일치 비율 |
| PURPOSE | 0.20 | 공고 요약·사업목적 vs 기업 요약·주요사업 코사인 최댓값 |
| PREFERENCE | 0.20 | 우대 요건 충족 비율 |

비교 대상이 없으면 0.5. 가중치와 규칙은 실행마다 `rule_snapshot` 에 저장한다.
테스트는 해시 임베더를 쓰므로 점수 크기는 참고용이다.

### 공개 조회

`GET /navigator/companies/{brn}/matches` 는 신용등급·매출 요건의 결과를 `null` 로 가리고, 그 요건을 빼고 판정과 연계이유를 다시 계산한다 (가린 요건 때문에 부적격이라는 사실이 드러나지 않도록). 보완질문은 주지 않는다.

## 화면

| 주소 | 대상 | 내용 |
|------|------|------|
| `/navigator` | 기업 | 사업자번호 조회 → 공개 정보, 추천 공고, 관리 링크 받기 |
| `/navigator/register` | 기업 | 신규 등록 |
| `/navigator/manage#t=…` | 기업 (관리 링크) | 탭: 추천 공고 / 보완질문 / 내 정보. 저장하면 재판정 |
| `/staff/navigator` | 담당자 (메뉴 "공고별 적합 기업") | 공고 목록 → 마지막 매칭 결과 → 다시 매칭, 기업 프로필 |

외부 확인값·내부 과제 등 기업이 고칠 수 없는 항목은 "(수정 불가)"로 표시한다. 특허는 KIPRIS 연동 전까지 보기만 된다.

## 테스트 데이터

사업자번호는 모두 가상(999-)이다. 관리 링크는 시드에 넣지 않으므로 `access-link` API 로 받는다.

| ID | 사업자번호 | 기업 | 비고 |
|----|-----------|------|------|
| 101 | 999-81-00015 | (가상)한빛전자통신 | 전술통신, 대전, 중소. 확인됨, R&D 이력 1건이 PRJ-2022-001 과 연결 |
| 102 | 999-82-00026 | (가상)누리복합소재 | 복합소재, 경남, 중견. 방산업체, 매출 자가입력 1,240억 vs DART(mock) 1,198억 |
| 103 | 999-83-00038 | (가상)새봄비전AI | 영상 AI, 경기, 창업. 미확인, 신용등급 자가입력, R&D 이력 없음 |

판정 결과 (`tests/test_navigator_matching.py` 에서 양방향 확인):

| 공고 | 한빛 | 누리 | 새봄 |
|------|------|------|------|
| 101 전술통신 부품국산화 (접수중) | 적합 | 부적격 (중견) | 부적격 (연구소) |
| 102 경량 방탄 복합소재 (접수중) | 부적격 (품질인증) | 적합 | 부적격 (업력·품질인증·신용) |
| 103 AI 영상 표적탐지 (접수중) | 부적격 (업력) | 부적격 (규모·업력) | 정보부족 (TRL), TRL 7 답하면 적합 |
| 104 강원 국방벤처 (접수전) | 부적격 | 부적격 | 부적격 |
| 105 하반기 국방 R&D (마감) | 정보부족 (보안측정) | 정보부족 (보안측정) | 정보부족 (주관 이력·휴폐업·보안측정) |

## 설정

| 이름 | 기본값 | 설명 |
|------|--------|------|
| `SOURCE_NTS_BIZ` | `mock` | `live` 는 아직 미구현 (미확인 처리) |
| `MAILER` | `mock` | mock 은 발송 없이 로그만 |
| `NAVIGATOR_PUBLIC_BASE_URL` | `http://localhost:5173` | 관리 링크 주소 |
| `NAVIGATOR_LINK_TTL_DAYS` | `30` | 관리 링크 유효기간 |
| `NAVIGATOR_RATE_LIMIT_PER_MINUTE` | `60` | 비로그인 API 제한 |
| `NAVIGATOR_DEV_EXPOSE_LINK` | `false` | `true` 면 응답에 관리 링크 포함. 로컬 전용 |

## 로컬 실행

```bash
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/relay_ax
./scripts/migrate.sh
for f in init_test_data navigator_companies navigator_announcements; do
  psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f seeds/$f.sql
done
(cd backend && NAVIGATOR_DEV_EXPOSE_LINK=true uvicorn app.main:app --reload --port 8000) &
(cd frontend && npm install && npm run dev)
```

API 확인:

```bash
curl -s localhost:8000/navigator/companies/999-83-00038/matches | jq '.recommendations[] | {announcement_title, verdict_label}'
T=$(curl -s -X POST localhost:8000/navigator/companies/999-83-00038/access-link | jq -r '.dev_management_link | sub(".*#t=";"")')
curl -s localhost:8000/navigator/manage/questions -H "X-Manage-Token: $T" | jq '.questions'
curl -s -X POST localhost:8000/navigator/matching/announcements/101 -H 'X-User-Id: 1' \
  | jq '.recommendations[] | {rank, company_name, verdict_label, total_score}'
```

화면 확인:

1. http://localhost:5173/navigator 에서 "(가상)새봄비전AI" 조회
2. "관리 링크 받기" → "[DEV] 관리 링크 열기" → 보완질문 탭에서 TRL 7 저장 → 103 공고가 적합으로 바뀜
3. http://localhost:5173/login 에서 기획자로 로그인 → "공고별 적합 기업" → 공고 선택 → 매칭 실행

## 미구현

- 공고문 자격요건 자동 추출 (`origin = AI_EXTRACTED` 컬럼만 있음)
- 외부 공고 수집 (기업마당, 나라장터, 방사청), 국세청 실연동, KIPRIS 특허 수집
- 실제 메일 발송, 신규 공고 알림
- 증빙 PDF 업로드 연결 (`evidence_document_id` 컬럼만 있음)
- 운영 임베딩 모델(bge-m3) 기준 가중치 조정
