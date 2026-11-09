# 프론트엔드 (Vite + React + TypeScript)

역할 선택 로그인과 역할별 화면 분기(RBAC UI)로 이어달리기 AX 의 업무 흐름과 권한 제어를 시연한다.

## 실행

```bash
# 1. 백엔드 (저장소 루트 README 의 '로컬 API 스모크 테스트' 1~3단계: 마이그레이션 → 시드 → uvicorn :8000)
# 2. 프론트엔드
cd frontend
npm install
npm run dev            # http://localhost:5173  (/api/* → http://localhost:8000 프록시)
```

백엔드 주소가 다르면 `API_PROXY_TARGET=http://host:port npm run dev`.
빌드 결과물(`npm run build` → `dist/`)을 백엔드와 다른 오리진에 올릴 때는 `VITE_API_BASE_URL` 을 지정하고 백엔드에 CORS 를 열어야 한다.

## 역할과 화면

| 역할 (X-User-Id) | 화면 묶음 | 메뉴 |
|---|---|---|
| PLANNER 기획자 (1) | 관리자 | 진행 현황 · 프로젝트 관리(수요 등록·AI 매칭·검토 배정) · 검토 큐 |
| DEPT_REVIEWER 조직 관리자·검수자 (2) | 관리자 | 진행 현황 · 프로젝트 관리 · 검토 큐 → 최종 판정 |
| EXPERT 전문가 (3) | 작업자 | 내 작업(배정된 검토) · 문서 업로드 |
| CURATOR 큐레이터·작업자 (4) | 작업자 | 내 작업(배정된 검토 + 초안 카드 발행) · 문서 업로드(→ 성과카드 초안) |

추천 상세(`/recommendations/:id`)는 모든 역할이 열고 의견을 남길 수 있다. 판정은 DEPT_REVIEWER·EXPERT, 최종 판정은 DEPT_REVIEWER 만 가능하다.

## 권한 처리 원칙

- **화면 분기는 편의, 권한 판단은 서버.** 메뉴·라우트는 역할로 나누지만(`src/auth/roles.ts`, `RequireRole`), 실제 허용 여부는 백엔드 `require_roles` 와 DB 트리거가 결정한다.
- 시연을 위해 일부 버튼(문서 등록, 매칭 실행, 최종 판정 등)은 권한 없는 역할에게도 보이며, 옆에 `🔒 ○○ 전용` 표시를 붙인다. 누르면 서버가 403 을 돌려주고 화면에 사유가 담긴 알림이 뜬다.
- 다른 역할의 화면 URL 로 직접 들어가면 '접근 권한 없음' 화면이 나온다.

## 구조

```
src/
  api/client.ts         fetch 래퍼: X-User-Id 자동 주입, 오류 → ApiError, 전역 오류 리스너
  api/endpoints.ts      백엔드 라우터와 1:1 호출 함수·응답 타입
  auth/roles.ts         역할 메타, 시드 사용자 1~4, 역할별 메뉴
  auth/AuthContext.tsx  로그인(GET /me 로 확인) · 역할 전환 · localStorage 복원
  auth/RequireRole.tsx  라우트 가드 (미로그인 → /login, 역할 불일치 → 접근 거부 화면)
  components/Toast.tsx  401/403/404/409/422/네트워크 오류를 사용자 문장으로 바꾸는 토스트
  components/Layout.tsx 상단 역할 전환 셀렉터 + 역할별 사이드 메뉴
  pages/admin/          DashboardPage, ProjectsPage, ReviewQueuePage
  pages/worker/         MyTasksPage, DocumentUploadPage
  pages/shared/         RecommendationPage (추천 근거·검토 판정·의견·이력)
  api/navigator.ts      Navigator API (기업 쪽은 X-User-Id 없음, 관리 링크는 X-Manage-Token)
  pages/navigator/      기업 화면 (로그인 없음): CompanySearchPage(/navigator), CompanyRegisterPage, CompanyManagePage(관리 링크)
  pages/admin/NavigatorStaffPage  담당자: 공고별 적합 기업 (/staff/navigator)
```

Navigator 화면 확인 순서는 `docs/navigator.md` 참고.

운영 전환 시 `api/client.ts` 의 X-User-Id 주입을 SSO 토큰(Authorization 헤더)으로, `LoginPage` 를 SSO 리다이렉트로 바꾸면 된다.

## 시연 시나리오 (약 5분)

1. **큐레이터(4)** 문서 업로드 → 본문 붙여넣기 → 문서 등록 → 성과카드 초안 저장 → 내 작업에서 `검수 완료·발행`
2. **전문가(3)** 로 전환 → 문서 업로드 시도 → 🔒 403 알림 (`필요 역할: CURATOR, PLANNER`)
3. **기획자(1)** 프로젝트 관리 → 기획수요 등록 → `AI 매칭 실행` → 1위 추천을 전문가·소관부서에 배정
4. **전문가(3)** 내 작업 → 검토하기 → `최종 판정으로 등록` 체크 후 제출 → 🔒 403 (DB 트리거: 최종판정 권한 없음) → 체크 해제하고 의견 등록
5. **검수자(2)** 검토 큐 → 검토하기 → 최종 판정(채택) → 진행 현황에서 근거 연결률·최종 검토율 확인

합성 데이터(`python -m app.synthetic load`)를 넣었으면 3단계는 새로 등록하지 않고 기존 기획수요를 고르면 된다.
- **`SYN-DM-D09` 광대역 재밍 대응 전술통신 안테나·제어기 패키지**를 추천한다. 정답(전술통신 고속 주파수도약 송수신기)의 소관부서가 무인미래통신기술팀(3)이라, 4·5단계의 소관부서 배정과 검수자(2) 최종 판정이 그대로 이어진다.
- 매칭 결과 위에 **상위 3건 카드**(연계유형 색 구분, 기준별 점수, 첫 원문 근거 인용)가 나오고, 아래에 전체 추천 표가 나온다.
- 같은 화면의 **🔍 R&D 성과물 검색**으로 결과보고서 문단을 의미 검색할 수 있다 (열람 권한이 있는 문서만).
- 다른 부서 소관 추천(예: 부품국산화사업팀)은 '소관부서' 버튼이 시드의 무인미래통신기술팀으로 배정하므로 시연에는 D09·D10 을 쓴다.
