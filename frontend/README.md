# 프론트엔드 (Vite + React + TypeScript)

## 실행

```bash
# 1. 백엔드 (저장소 루트 README 의 '로컬 실행' 1~3단계)
# 2. 프론트엔드
cd frontend
npm install
npm run dev            # http://localhost:5173  (/api/* → http://localhost:8000 프록시)
```

백엔드 주소가 다르면 `API_PROXY_TARGET=http://host:port npm run dev`.
빌드 결과물(`npm run build` → `dist/`)을 다른 오리진에 올릴 때는 `VITE_API_BASE_URL` 을 지정하고 백엔드에 CORS 를 연다.

## 화면

| 사용자 | 주소 | 화면 |
|---|---|---|
| 기업 (로그인 없음) | `/navigator` | 사업자번호 조회 → 지원 가능 공고 · 참여할 수 있었던 사업 · 알림 · 회사 정보 (이메일 확인 코드로 열기) |
| 기업 | `/navigator/register` | 회사 등록 |
| 기관 담당자 (`/login`) | `/staff/navigator` | 공고별 적합 기업, 참여 권유 |
| 기관 담당자 | `/staff/announcements` | 공고 등록·조건 확인 |
| 기관 담당자 | `/staff/sources` | 외부 수집 |

표기 기준은 [docs/navigator_ux.md](../docs/navigator_ux.md). 실제 권한은 백엔드가 판단한다 (`require_roles("STAFF")`).
