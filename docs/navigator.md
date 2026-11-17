# Navigator

기업이 사업자번호로 지원 가능한 공고를 찾고, 기관 담당자가 공고별로 적합 기업을 보는 기능.
기업은 로그인 없이 쓴다. 회사 정보 화면은 사업자번호로 조회한 뒤 등록 이메일로 받은 6자리 확인 코드를 넣어야 열린다. 담당자는 기존 로그인을 쓴다.

## 구성

| 구분 | 위치 |
|------|------|
| 마이그레이션 | 0019 기업 프로필(특허·인증·신용등급·R&D 이력·관리 링크), 0020 외부 출처·값 출처, 0021 공고·자격요건, 0022 임베딩·매칭 결과, 0024 알림 구독, 0025 외부 수집(기업마당 출처, 출처별 기업 식별자), 0030 국기원 공지사항 출처·공고 첨부, 0031 공고 조건 확인 표시, 0033 기업 제품·보유 기술·지원사업 이력·증빙 (0032 는 다른 작업이 사용), 0034 참여 권유, 0035 회사 정보 확인 코드 |
| 기업 API | `backend/app/routers/navigator.py` |
| 공고 API | `backend/app/routers/announcements.py`, 요건 형식 `backend/app/schemas/announcements.py` (`RULE_MODELS`) |
| 매칭 API | `backend/app/routers/navigator_matching.py` |
| 알림 | `backend/app/routers/navigator_alerts.py`, `backend/app/services/navigator_alerts.py` |
| 판정 | `backend/app/services/eligibility.py` (DB 없이 테스트 가능한 순수 함수) |
| 매칭 | `backend/app/services/navigator_matching.py`, 벡터 `navigator_embedding.py` |
| 외부 수집 | 연결 부품 `backend/app/services/external/{nts,kipris,dart,bizinfo}.py` (mock 데이터 `fixtures/*_mock.json`), 실행 `services/collector.py`, API `routers/navigator_sources.py`, 명령 `python -m app.collect` |
| 관리 링크 / 메일 | `services/access_link.py` / `services/mailer.py` |
| 화면 | `frontend/src/pages/navigator/`, `frontend/src/pages/admin/NavigatorStaffPage.tsx`, `NavigatorSourcesPage.tsx`, 표기 기준 [navigator_ux.md](navigator_ux.md) |
| 테스트 데이터 | `seeds/navigator_companies.sql`, `seeds/navigator_announcements.sql` (재실행 가능) |
| 검증 | 가상 기업 20곳 × 공고 5건 정답 `seeds/navigator_eval/corpus.json`, 측정 `python -m app.navigator_eval`, 결과 [navigator_eval.md](navigator_eval.md) |

기존 테이블은 컬럼 추가만 했다. 사업자번호는 `organization.business_reg_no` 를 숫자 10자리로 쓴다.
기존 코드 변경은 `routers/documents.py` 의 문서 저장 부분을 `store_document`, `parse_file` 로 분리한 것과 `reembed` 에 새 벡터 테이블을 추가한 것뿐이다.

## API

### 기업 (로그인 없음)

| 메서드·경로 | 인증 | 설명 |
|-------------|------|------|
| `POST /navigator/companies` | - | 등록. 사업자번호 검증 → 국세청 진위확인 → 저장. 응답 `manage_token` 으로 등록한 사람이 바로 회사 정보 화면을 연다 |
| `GET /navigator/companies/{brn}` | - | 공개 정보: 상호, 진위확인 결과, 휴·폐업, 특허 |
| `GET /navigator/companies/{brn}/matches` | - | 공개 정보 기준 추천 공고 (아래 '공개 조회' 참고) |
| `POST /navigator/companies/{brn}/login-code` | - | 등록 이메일로 확인 코드 6자리 발송 (10분 유효, 1분에 한 번). `NAVIGATOR_DEV_EXPOSE_LINK=true` 면 응답에 `dev_code` |
| `POST /navigator/companies/{brn}/login` | - | `{"code":"123456"}` 맞으면 관리 토큰. 틀림 400, 만료·사용함·5번 틀림 410 |
| `POST /navigator/companies/{brn}/access-link` | - | 관리 링크 재발송. 등록 이메일로만 보냄 |
| `GET /navigator/manage/profile` | 관리 링크 | 전체 프로필 (신용등급, 매출, 인증, R&D 이력, 제품, 보유 기술, 지원사업 이력, 증빙, 값 출처) |
| `PATCH /navigator/manage/profile` | 관리 링크 | 수정. 보낸 필드만 반영, 출처는 SELF. 목록(`products`·`technologies`·`support_history` 포함)은 자가입력 행만 교체 |
| `POST /navigator/manage/evidence` | 관리 링크 | 증빙 파일(PDF·HWP·HWPX) → 종류·번호·날짜·등급을 뽑아 반환. 같은 파일은 한 번만 |
| `DELETE /navigator/manage/evidence/{id}` | 관리 링크 | 증빙 삭제 (연결된 인증·등급은 증빙 없음으로) |
| `POST /navigator/manage/matches?include_closed=&refresh=` | 관리 링크 | 내 추천 공고. 당일 결과가 있고 이후 변경이 없으면 재사용 |
| `POST /navigator/manage/past-matches?refresh=` | 관리 링크 | 참여할 수 있었던 사업: 최근 마감 공고 중 적합·확인 필요. 공고마다 `next_round`(같은 사업의 지금 열린 공고), `participated` |
| `GET /navigator/manage/questions` | 관리 링크 | 보완질문 (부적격 공고 제외, 요건당 1회). `answer_type`: `integer` / `boolean` |
| `POST /navigator/manage/answers` | 관리 링크 | `{"answers":[{"requirement_id":1,"value":7}]}` 저장 후 재판정 결과 반환 |

관리 링크는 `X-Manage-Token` 헤더로 보낸다.

### 공고

| 메서드·경로 | 인증 | 설명 |
|-------------|------|------|
| `GET /navigator/announcements?receipt_state=&q=&review=` | - | 목록. 비로그인은 PUBLISHED 만. 담당자는 `review=PENDING`(조건 확인 전)·`DONE` |
| `GET /navigator/announcements/{id}` | - | 상세 (자격요건, 원문 인용·쪽, 요구기술) |
| `GET /navigator/announcements/{id}/chunks?q=` | - | 공고문 원문 청크 |
| `POST /navigator/announcements` | 담당자 | 직접 등록. 요건 하나라도 형식 오류면 전체 롤백 |
| `POST /navigator/announcements/upload` | 담당자 | 공고문 PDF → 원문 청크 저장 → DRAFT 공고 |
| `PATCH /navigator/announcements/{id}` | 담당자 | 수정. `status` 로 PUBLISHED / CANCELLED |
| `POST .../requirements`, `PATCH`·`DELETE .../requirements/{rid}` | 담당자 | 자격요건 (`evidence.chunk_id` 로 원문 연결) |
| `POST .../tech-needs`, `DELETE .../tech-needs/{tid}` | 담당자 | 요구기술 |
| `POST /navigator/announcements/text` | 담당자 | 공고문 글자를 붙여 넣어 작성중 공고 만들기 |
| `GET /navigator/announcements/{id}/source` | 담당자 | 게시글 본문 + 첨부에서 뽑은 글자 (PDF 로 올린 공고는 청크를 이어 붙임) |
| `POST /navigator/announcements/{id}/extract` | 담당자 | 조건·접수기간·지원 한도·지원 기간·대상·목적 후보. 저장 안 함 |
| `PUT /navigator/announcements/{id}/review` | 담당자 | 확인 저장: 공고 칸 수정 + 조건·요구기술 통째 교체 + 확인 표시, `publish: true` 면 공개(조건 0개면 422) |
| `GET /navigator/announcements/requirement-types` | 담당자 | 조건 종류·인증 코드 |

담당자 = `PLANNER` 또는 `ADMIN`. 접수 상태(UPCOMING / OPEN / CLOSED)는 날짜로 계산한다 (`v_announcement`).

### 매칭 (담당자)

| 메서드·경로 | 설명 |
|-------------|------|
| `POST /navigator/matching/announcements/{id}?verdict=` | 공고 → 기업 매칭 실행 |
| `GET /navigator/matching/announcements/{id}` | 해당 공고의 마지막 실행 결과 (없으면 `run: null`) |
| `POST /navigator/matching/companies/{org_id}?include_closed=&past=` | 기업 → 공고 매칭. `past=true` 면 최근 마감 공고만 |
| `GET /navigator/matching/companies/{org_id}/profile` | 기업 프로필 (이메일 마스킹) |
| `GET /navigator/matching/runs/{run_id}` | 저장된 실행 조회 |

### 알림

| 메서드·경로 | 인증 | 설명 |
|-------------|------|------|
| `GET /navigator/manage/subscriptions` | 관리 링크 | 수신자 목록 |
| `POST /navigator/manage/subscriptions` | 관리 링크 | 수신자 추가 `{email, keywords, min_score, include_needs_info, channels}` |
| `PATCH`·`DELETE /navigator/manage/subscriptions/{id}` | 관리 링크 | 설정 변경, 켜기·끄기(`is_active`), 삭제 |
| `POST /navigator/manage/subscriptions/{id}/confirm-mail` | 관리 링크 | 확인 메일 재발송 (미확인·수신 거부 상태만) |
| `GET /navigator/manage/alerts` | 관리 링크 | 화면 알림 (공고당 1건), `unread` |
| `POST /navigator/manage/alerts/read` | 관리 링크 | 읽음 처리 `{announcement_ids}` (생략하면 전체) |
| `POST /navigator/subscriptions/confirm` | 메일 링크 | `{token}` 수신 확인 |
| `POST /navigator/subscriptions/unsubscribe` | 메일 링크 | `{token}` 수신 거부 |
| `PUT /navigator/manage/outreach-consent` | 관리 링크 | `{consent}` 기관 담당자의 참여 권유 메일 받기 |
| `POST /navigator/outreach/optout` | 메일 링크 | `{token}` 참여 권유 수신 거부 (동의 해제) |
| `GET /navigator/matching/announcements/{id}/outreach` | 담당자 | 마지막 매칭의 적합·확인 필요 기업, 권유 동의, 보낸 기록 |
| `POST /navigator/matching/announcements/{id}/outreach` | 담당자 | `{organization_ids, note}` 권유 메일. 못 보낸 기업은 `skipped` 에 이유 |
| `GET /navigator/alerts/announcements/{id}` | 담당자 | 공고별 발송 현황 (받는 사람은 가린 주소) |
| `POST /navigator/alerts/announcements/{id}` | 담당자 | 아직 안 보낸 구독 기업에 발송 |

결과 행: `rank`, `verdict`, `total_score`, `scores`, `checks`(요건별 판정·사유·보완질문·원문), `questions`, `evidence`, `rationale`.

### 외부 수집 (담당자)

| 메서드·경로 | 설명 |
|-------------|------|
| `GET /navigator/sources` | 출처별 모드(mock/live), 주기, 마지막 수집 결과, 다음 주기 |
| `GET /navigator/sources/jobs?source=` | 수집 기록 |
| `POST /navigator/sources/{code}/run?organization_id=` | 지금 수집. 기업 지정은 NTS_BIZ·KIPRIS·DART 만 |
| `GET /navigator/sources/companies/{org_id}/external-ids` | 기업의 DART 고유번호·KIPRIS 특허고객번호 |
| `PUT /navigator/sources/companies/{org_id}/external-ids/{code}` | 동명 회사가 섞일 때 직접 지정 `{external_id}` |

## 외부 수집

| 코드 | 출처 | 주기 | 반영 |
|------|------|------|------|
| `NTS_BIZ` | 국세청 사업자 상태조회 | 30일 | `company_profile.business_status`, 값 출처(확인됨). 100건씩 묶어 조회 |
| `KIPRIS` | KIPRIS Plus | 7일 | `company_patent` (origin EXTERNAL, 확인됨). 같은 출원번호의 자가입력 행은 외부값으로 바뀜 |
| `DART` | OpenDART | 30일 | 매출·직원 수·기준연도를 값 출처(확인됨)로. 판정은 확인된 외부값 우선 |
| `BIZINFO` | 기업마당 지원사업 | 1일 | `announcement` 작성중(DRAFT, source_kind EXTERNAL). 담당자가 요건 입력 후 공개하면 알림 |
| `KRIT` | 국방기술진흥연구소 공지사항 (www.krit.re.kr) | 1일 | `announcement` 작성중 + 본문(`body_text`)·게시일·묶음 키, 첨부 글자는 `announcement_attachment` |

- 한 번 실행 = `external_fetch_job` 1행, 받은 원본은 `external_raw_record` 에 그대로. 실패하면 반영은 롤백하고 FAILED 와 오류를 남긴다.
- 주기 실행: `python -m app.collect --due` 를 cron 으로 (예: 매시간). 출처별 마지막 주기 실행 뒤 `fetch_interval` 이 지난 것만 돈다.
- KIPRIS 는 사업자번호 검색이 없어 출원인 이름이 정확히 같은 것만 가져오고, 처음 찾은 특허고객번호를 저장해 다음부터 그 번호로 찾는다.
- DART 는 회사명으로 후보를 찾고 `company.json` 의 사업자번호가 같은 것을 고유번호로 저장한다. 상장·외부감사 대상만 있다.
- 기업마당 공고는 `NAVIGATOR_ANNOUNCEMENT_KEYWORDS` 가 제목·요약·해시태그에 있는 것만. 공고번호는 `BIZINFO-<공고ID>`, 작성중일 때만 갱신.
- 국기원 공지사항은 키 없이 게시판을 읽는다. 제목으로 기업 대상 모집 공고만 고르고(결과·설명회·대학·채용 등 제외) 공고번호는 `KRIT-<게시글 번호>`.
  - 신청기간은 본문의 "신청기간 : ’26. 11. 5.(목) ~ 11. 12.(목)" 같은 줄에서, 본문에 없으면 첨부 글자에서 찾는다.
  - 첨부는 HWP·HWPX·PDF 만 받아 글자를 뽑는다(`app/services/hwp_text.py`). 원본 파일은 저장하지 않는다. zip·xlsx·이미지는 SKIPPED, 배포용 HWP·스캔 PDF 는 UNSUPPORTED.
  - `series_key` 는 제목에서 차수·연도·재공고·연장 표시를 지운 값. 같은 사업의 여러 공고를 묶는다.
  - 평소에는 앞 `KRIT_MAX_PAGES`(3) 쪽만 읽고 이미 받은 공고는 건너뛴다. 처음 채울 때는 `KRIT_MAX_PAGES=61 SOURCE_KRIT=live python -m app.collect --source KRIT` (2021년 6월부터 약 600건, 요청 사이 0.5초라 수십 분 걸림).
  - 게시판에 동시에 여러 요청을 보내면 빈 페이지가 와서 한 건씩 받는다. 상세는 목록에서 받은 쿠키와 Referer 가 있어야 열린다.

### 조건 뽑기 (`app/services/requirement_extract.py`)

- `REQUIREMENT_EXTRACTOR=auto`(기본)는 LLM 자격증명이 있으면 LLM, 없으면 규칙. `rules` 는 외부로 보내는 것 없음.
- 규칙: 신청자격·신청제한·우대 구역을 나눠 기업규모, 휴·폐업, 체납·부도·참여제한, 연구소·인증, 신용등급, 업력, 지역, TRL, 우대 특허·수출만 찾는다. 지원 한도는 "기업당·한도·최대" 줄에서, 총 예산은 뺀다.
- "2. 지원대상: 중소기업 (…)" 처럼 제목과 내용이 한 줄이면 콜론 앞을 제목으로 보고 구역을 정한다. 요구기술은 "요구기술:"·"개발 대상 기술:" 줄만 쉼표로 나눠 뽑는다 ("지원분야"는 컨설팅 분야 같은 것이 섞여 안 씀).
- LLM: 공고문 글자(최대 4만 자)와 조건 코드표를 보내 JSON 으로 받는다. 규칙 형식이 틀리거나 목록에 없는 인증이면 '기타'로 바꾸고 경고. 근거 문장이 공고문에 그대로 없으면 `quote_found=false`.
- 뽑은 것은 후보일 뿐이다. 담당자가 원문과 대조해 저장해야 `origin = AI_EXTRACTED` 로 들어가고, 공개해야 기업 추천·알림에 쓰인다.
- 실제 국기원 공고 19건에 규칙을 돌려 보면 대부분 기업규모·휴폐업·결격사유가 나오고, 방산혁신클러스터 공고는 지역이 나온다. "다음 각 호 중 하나" 같은 조건은 규칙으로 못 뽑으니 '기타'로 직접 넣는다.

- live 연결 부품은 공개 문서의 응답 모양으로 해석을 테스트했지만 실제 키로는 아직 호출해 보지 않았다 (개발 환경에서 외부 API 차단). 키를 받으면 `SOURCE_<코드>=live` 로 한 출처씩 확인한다.
- NICE·KED(유료 계약), NTIS(비용 확인), 인증서 PDF 는 연결 부품이 없다. 화면에 "미연결"로 표시.

## 등록 규칙

- 진위확인 일치: 저장, "확인됨".
- 불일치(등록부에 있으나 대표자명·개업일 다름): 422, 저장 안 함. 수집 기록은 남김.
- 확인 불가(등록부에 없음, 연결 안 됨): 저장, "미확인".
- 사업자번호당 1개. 중복은 409.
- 기관 DB 에 이미 있는 기업(이메일 없음)은 진위확인 일치일 때만 이어서 등록.
- 이메일 필수.
- 비로그인 API 는 IP 당 분당 `NAVIGATOR_RATE_LIMIT_PER_MINUTE` 회 (프로세스 메모리 기준).

### 회사 정보 화면 열기

- 등록한 사람은 등록 응답의 토큰으로 바로 연다.
- 그 뒤에는 사업자번호 조회 → '회사 정보 입력·수정' → 등록 이메일로 온 6자리 코드. 코드는 해시만 저장, 10분 유효, 1분에 한 번 발송, 새 코드를 받으면 이전 코드는 무효, 5번 틀리면 그 코드는 끝.
- 등록 이메일이 없는 기업(기관 DB 에만 있는 기업)은 409. 담당자가 이메일을 넣어 줘야 한다.
- 로컬 시연은 `NAVIGATOR_DEV_EXPOSE_LINK=true` 면 화면에 코드를 미리 채운다.

## 기업 입력 항목

- 제품(`company_product`)과 보유 기술(`company_technology`, TRL 1~9)은 매칭에서 요구 기술과 비교하는 TECH 벡터로 들어간다. 근거 표시는 "제품"·"보유기술".
- 지원사업 참여 이력(`company_support_history`)은 컨설팅·수출·시험평가처럼 R&D 과제가 아닌 지원사업. R&D 수행 경험 판정에는 넣지 않는다.
- 증빙(`company_evidence`): 원본 파일은 저장하지 않고 뽑은 글자와 값만 둔다. 서버에 OCR 이 없어 사진·스캔본은 UNSUPPORTED, 값은 직접 입력.
  - 알아보는 것: 벤처기업확인서, 기업부설연구소·연구개발전담부서 인정서, 이노비즈·메인비즈, ISO 9001, AS9100, 국방품질경영, 방산업체 지정, 중소기업 확인서, 신용평가 등급확인서(NICE·KED).
  - 뽑은 값은 입력란을 채우기만 한다. 기업이 확인하고 저장하면 인증·등급 행에 `company_evidence_id` 로 연결된다. 다른 회사 증빙 번호는 연결되지 않는다.
  - 신용평가서가 섞이므로 기업 본인과 기관 담당자만 본다.

### 역량 레이더

회사 정보 화면과 담당자 기업 상세에 6축(0~100)으로 보여 주고, 프로필이 있는 전체 기업의 축별 평균을 점선으로 겹친다 (`app/services/company_radar.py`).

| 축 | 계산 |
|----|------|
| 신용 | 가장 최근 신용등급 서열 / 22 (AAA = 100). 등급이 없으면 미입력 |
| 특허 | 등록 20점, 출원 10점 (소멸 제외) |
| 인증 | 유효한 인증 1건 25점 |
| 기술 | 보유 기술 1건 15점(최대 45) + 최고 TRL / 9 × 55 |
| 제품 | 제품 1건 20점, 국방 제품은 20점 더 |
| 사업참여 | 지원사업 성공·완료 25, 선정 15, 신청·탈락 5 / R&D 주관 25, 참여 15 |

모든 축은 100에서 자른다. 매칭 순위에는 쓰지 않는다.

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

순서는 A안: 자격요건 판정(적합 → 확인 필요 → 부적합)으로 먼저 나누고, 같은 판정 안에서는 벡터 관련도 순.
관련도가 같으면 우대 요건 충족 비율, IPC 일치 순으로 정한다. 담당자 화면은 판정별 목록으로 나눠 각각 관련도 순으로 보여 준다.

| 기준 | vector (기본) | weighted (이전) | 계산 |
|------|------|------|------|
| TECH | 0.7 | 0.45 | 요구기술별로 기업 보유기술·제품·특허·R&D·주요사업 중 최대 코사인 유사도, 핵심 요구기술 ×2 가중평균 |
| IPC | - | 0.15 | 요구기술 IPC 와 기업 특허 IPC 4자리 일치 비율 |
| PURPOSE | 0.3 | 0.20 | 공고 요약·사업목적 vs 기업 요약·주요사업 코사인 최댓값 |
| PREFERENCE | - | 0.20 | 우대 요건 충족 비율 |

vector 모드는 비교 대상이 없는 기준을 빼고 남은 가중치로 다시 나눈다 (요구기술이 없는 공고는 PURPOSE 만).
IPC·우대 점수는 계산해서 근거와 동점 처리에 쓴다. `NAVIGATOR_RANKING=weighted` 로 이전 가중합으로 돌릴 수 있다.
weighted 모드는 비교 대상이 없으면 0.5. 정렬 방식·가중치·규칙은 실행마다 `rule_snapshot` 에 저장하고, 오늘 실행 결과를 다시 쓸 때도 같은 방식인지 본다.
테스트는 해시 임베더를 쓰므로 점수 크기는 참고용이다.

### 알림 규칙

- 공고가 PUBLISHED 로 등록되거나 PUBLISHED 로 바뀌면 발송한다. 접수전·접수중 공고만.
- 구독 기업만 판정한다 (`requested_via = SYSTEM` 실행). 이 실행은 담당자 화면의 '마지막 매칭'에 쓰지 않는다.
- 보내는 조건: 적합 (정보부족은 `include_needs_info` 일 때), 총점 ≥ `min_score`, 관심 분야가 비었거나 공고 제목·개요·요구기술에 하나라도 포함.
- 등록 이메일은 등록할 때 기본 설정(전체 분야, 확인 필요 포함, 화면+메일)으로 바로 수신자가 된다. 끄거나 지우는 건 알림 탭에서.
- 수신자: 관리 링크를 받은 주소는 바로 시작. 다른 주소는 그 주소로 확인 메일(3일 유효)을 보내고, 열어야 시작. 기업당 5명.
- 같은 수신자에게 같은 공고는 한 번만. 메일마다 수신 거부 링크(1회용 토큰, 해시만 저장)를 넣는다.
- 수신 거부한 주소는 기업이 켤 수 없고, 확인 메일을 다시 받아 수신자가 열어야 살아난다.
- 메일은 커밋 후 보낸다. 실패하면 FAILED 로 남기고 공고 등록은 그대로 성공. 화면 알림은 남는다.
- 메일에는 판정·총점·연계이유만 넣고 신용등급 값은 넣지 않는다.

### 참여 권유

- 기업이 알림 탭에서 "참여 권유 메일 받기"를 켜야 보낸다 (`company_profile.outreach_consent_at`). 받는 주소는 등록 이메일.
- 담당자는 공고의 마지막 매칭 결과(담당자 실행)에서 적합·확인 필요 기업만 고를 수 있다. 접수중·접수 예정 공고만.
- 같은 공고·기업에는 한 번만 (`outreach_message`). 실패한 것만 다시 보낼 수 있다.
- 메일: 공고명, 접수 기간, 판정과 필수 조건 충족 수, 담당자 메모, 공개 조회 링크, 보낸 사람. 담당자 이메일이 있으면 Reply-To 로 넣는다. 신용등급 값은 넣지 않는다.
- 메일마다 수신 거부 링크(1회용 토큰, 해시만 저장). 누르면 동의가 풀린다.
- 메일은 커밋 후 보낸다. 실패하면 FAILED 로 남고 화면에 표시된다.

### 메일 발송

- `MAILER=mock`(기본)은 보내지 않고 메모리에만 쌓는다. `MAILER=smtp` 면 아래 SMTP 설정으로 보낸다.
- 설정 확인: `cd backend && python -m app.services.mailer 받는주소@example.com`
- Gmail 은 2단계 인증 후 앱 비밀번호를 `SMTP_PASSWORD` 에 넣는다 (`smtp.gmail.com`, 587, starttls). 사내 메일 서버는 담당 부서에 호스트·포트·계정을 받는다.
- 관리 링크 재발송·수신 확인 메일이 실패하면 503 으로 알린다. 등록 완료 메일과 공고 알림·권유 메일은 실패해도 요청은 성공하고 기록만 남긴다.

### 참여할 수 있었던 사업

- 대상: 마감일이 오늘부터 `NAVIGATOR_PAST_YEARS`년(기본 2년) 안인 마감 공고. 회사 개업일 전에 마감된 공고는 뺀다.
- 판정은 각 공고 마감일 기준(업력·인증 유효기간 등)이지만 회사 정보는 지금 값이다. 화면에 "마감 당시와 다를 수 있음"을 적는다.
- 기업에게는 적합(지원할 수 있었음)과 확인 필요만 보여 준다. 순서는 현재 공고와 같은 A안.
- 같은 `series_key`(차수·재공고 묶음)의 접수중·접수 예정 공고가 있으면 "다음 회차"로 붙인다. 국기원 수집 공고는 제목으로 키를 만든다.
- 기업이 지원사업 이력에 그 공고를 연결해 두었으면 "참여함"으로 표시한다.
- 실제 선정 여부는 모른다. 국기원 내부 선정 목록은 받지 않으므로, 확인하려면 공개된 선정결과 글로만 본다.

### 공개 조회

`GET /navigator/companies/{brn}/matches` 는 신용등급·매출 요건의 결과를 `null` 로 가리고, 그 요건을 빼고 판정과 연계이유를 다시 계산한다 (가린 요건 때문에 부적격이라는 사실이 드러나지 않도록). 보완질문은 주지 않는다.

## 화면

| 주소 | 대상 | 내용 |
|------|------|------|
| `/navigator` | 기업 | 사업자번호 조회 → 공개 정보, 추천 공고, 관리 링크 받기 |
| `/navigator/register` | 기업 | 신규 등록 |
| `/navigator/manage#t=…` | 기업 (관리 링크) | 탭: 지원 가능 공고 / 참여할 수 있었던 사업 / 알림 / 회사 정보(맨 위 역량 레이더). 저장하면 재판정 |
| `/navigator/subscriptions/confirm#t=…`, `/navigator/unsubscribe#t=…`, `/navigator/outreach/optout#t=…` | 메일 수신자 | 수신 확인, 알림 수신 거부, 참여 권유 수신 거부 |
| `/staff/announcements` | 담당자 (메뉴 "공고 등록·조건 확인") | 확인 전 / 확인 완료 공고 → 왼쪽 원문(본문·첨부 글자), 오른쪽 조건 뽑기 → 접수기간·지원 한도·조건·요구기술 고치기 → 확인 저장 또는 공개. 공고문 붙여넣기 등록 |
| `/staff/navigator` | 담당자 (메뉴 "공고별 적합 기업") | 공고 목록 → 마지막 매칭 결과(적합 / 정보부족 / 부적격 목록을 따로 총점 순, 부적격은 접힘) → 다시 매칭, 기업 프로필, 참여 권유(동의 기업 선택·메모·보낸 기록), 구독 기업 알림 현황 |
| `/staff/sources` | 담당자 (메뉴 "외부 수집") | 출처별 모드·주기·마지막 결과, 지금 수집, 수집 기록 |

외부 확인값·내부 과제 등 기업이 고칠 수 없는 항목은 "(수정 불가)"로 표시한다. 특허는 기업이 직접 고치지 않고 KIPRIS 수집으로 들어온다.

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

`seeds/navigator_past_announcements.sql` 은 시연용으로 106(101 의 이전 회차, 2025-12-15 마감, 요건 같음)을 넣고 101 과 같은 `series_key` 로 묶는다. 한빛의 "참여할 수 있었던 사업"에 106 이 적합으로, 다음 회차로 101 이 나온다.

## 설정

| 이름 | 기본값 | 설명 |
|------|--------|------|
| `SOURCE_NTS_BIZ`, `SOURCE_KIPRIS`, `SOURCE_DART`, `SOURCE_BIZINFO` | `mock` | `live` 면 실제 API. 키가 없으면 수집은 FAILED, 등록 진위확인은 미확인 |
| `NTS_SERVICE_KEY` | - | 공공데이터포털 국세청 사업자등록정보 (일반 인증키) |
| `KIPRIS_ACCESS_KEY` | - | KIPRIS Plus |
| `DART_API_KEY` | - | OpenDART |
| `BIZINFO_API_KEY` | - | 기업마당 |
| `SOURCE_KRIT` | `mock` | `live` 면 국기원 공지사항을 직접 읽음 (키 불필요) |
| `KRIT_MAX_PAGES` | `3` | 한 번에 읽을 쪽 수 (쪽당 10건). 처음 채울 때 61 |
| `KRIT_REQUEST_DELAY_S` | `0.5` | 국기원 요청 사이 대기 |
| `NAVIGATOR_PAST_YEARS` | `2` | 참여할 수 있었던 사업에서 볼 마감 공고 기간(년) |
| `NAVIGATOR_RANKING` | `vector` | 같은 판정 안의 순서. `vector` = 벡터 관련도(A안), `weighted` = 이전 가중합 |
| `REQUIREMENT_EXTRACTOR` | `auto` | 공고 조건 뽑기. `auto` 는 LLM 키가 있으면 LLM (`LLM_PROVIDER`·`LLM_MODEL` 따름), `rules` 는 규칙만 |
| `NAVIGATOR_ANNOUNCEMENT_KEYWORDS` | `국방,방산,방위산업,방위사업,무기체계,군수` | 외부 공고 거르기 (쉼표). "방위"만 쓰면 "주방위생" 같은 공고가 걸림 |
| `MAILER` | `mock` | mock 은 발송 없이 로그만 (본문은 DEBUG 로그), smtp 는 실제 발송 |
| `SMTP_HOST`, `SMTP_PORT` | -, `587` | SMTP 서버 |
| `SMTP_USER`, `SMTP_PASSWORD` | - | 로그인 계정. 비우면 로그인 없이 보냄 |
| `SMTP_FROM`, `SMTP_FROM_NAME` | `SMTP_USER`, `Navigator` | 보내는 주소·이름 |
| `SMTP_SECURITY` | `starttls` | `starttls`(587) / `ssl`(465) / `none` |
| `SMTP_TIMEOUT_S` | `15` | 연결 제한 시간 |
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

외부 수집 (mock):

```bash
(cd backend && python -m app.collect --source KIPRIS)   # 또는 --due
curl -s localhost:8000/navigator/sources -H 'X-User-Id: 1' | jq '.[] | {code, mode, last_status, last_result}'
```

화면 확인:

1. http://localhost:5173/navigator 에서 "(가상)새봄비전AI" 조회
2. "회사 정보 입력·수정" → (회사 정보 탭 "자동 채우기") → 확인 필요 공고 카드에서 TRL 7 저장 → 103 공고가 적합으로 바뀜
3. 알림 탭 → 추가 → 저장 (등록 이메일은 바로 '받는 중'). 다른 주소를 추가하면 "[DEV] 확인 링크 열기"
4. 공고를 PUBLISHED 로 등록하면 (예: 아래) 알림 탭에 새 공고가 뜬다
5. http://localhost:5173/login 에서 기획자로 로그인 → "공고별 적합 기업" → 공고 선택 → 매칭 실행, 아래 '구독 기업 알림'
6. "외부 수집" → KIPRIS "지금 수집" → 한빛 특허 3건이 외부 확인으로 바뀜

```bash
curl -s -X POST localhost:8000/navigator/announcements -H 'X-User-Id: 1' -H 'Content-Type: application/json' -d '{
  "announcement_no":"LOCAL-001","title":"전술 데이터링크 모뎀 국산화","agency_name":"(가상)기관",
  "receipt_start":"2026-11-01","receipt_end":"2026-12-31","summary":"전술 데이터링크 통신 모뎀 부품 국산화",
  "requirements":[{"req_type_code":"COMPANY_SIZE","rule":{"allowed":["SME","STARTUP","VENTURE"]},"description":"중소기업"}],
  "tech_needs":[{"tech_name":"전술 데이터링크 통신 모뎀","ipc_codes":["H04B"]}]}'
```

## 미구현

- 실제 LLM 키로 조건 뽑기 정확도 측정 (지금은 규칙으로만 실공고 확인)
- 실제 키로 live 연결 확인 (국세청 → KIPRIS → DART → 기업마당 순서)
- 나라장터·방사청 공고, NICE·KED 신용등급, NTIS 과제 연결 부품
- 등록할 때 이메일 소유 확인 (지금은 등록한 사람이 넣은 주소를 그대로 믿음. 국세청 진위확인으로만 거름)
- 알림 발송을 큐로 분리 (지금은 공고 등록 요청 안에서 처리)
- 사진·스캔 증빙 OCR (지금은 PDF·한글 파일 글자만 읽음)
- 운영 임베딩 모델(bge-m3) 기준 순위 재측정·가중치 조정
