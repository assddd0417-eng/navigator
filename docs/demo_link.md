# 시연 주소 만들기

코드 없이 링크 하나로 Navigator 를 보여 줄 때 쓴다.

- 데이터: 가상 기업 3곳 · 공고 5건(+지난 공고)만 들어간다. 운영 DB 와 따로 둔다.
- 접근: 주소 전체에 아이디·비밀번호(브라우저 기본 인증). `SITE_USER`(기본 `navigator`) / `SITE_PASSWORD`.
- 메일: 보내지 않는다(`MAILER=mock`). 확인 코드는 화면에 미리 채워진다.
- 관련도 계산: 가벼운 해시 임베더(`EMBEDDER=hash`). 맥 운영 서버(bge-m3)와 관련도 순서가 다를 수 있다.

두 가지 방법 중 하나를 고른다.

| | A. Render (무료 호스팅) | B. 맥북 + 임시 주소 |
|---|---|---|
| 가입 | Render 계정 (GitHub 로그인) | 없음 |
| 비용 | 무료 | 무료 |
| 주소 | `https://navigator-demo-xxxx.onrender.com` 고정 | `https://xxxx.trycloudflare.com`, 켤 때마다 바뀜 |
| 유지 | 맥과 무관하게 계속 열림 | 맥이 켜져 있고 창을 닫지 않는 동안만 |
| 제약 | 15분 안 쓰면 잠들고 첫 접속에 1분 정도 걸림. 무료 DB 는 30일 후 만료(다시 만들면 됨) | 맥 절전 시 끊김 |

## A. Render

1. https://render.com 에서 **GitHub 로 가입**하고, navigator 저장소 접근을 허용한다.
2. 대시보드 **New → Blueprint** → `assddd0417-eng/navigator` 선택. 저장소의 `render.yaml` 을 읽어 웹 서버와 DB 를 함께 만든다.
3. `SITE_PASSWORD` 입력란에 비밀번호를 넣고 **Apply**.
4. 첫 빌드 5~10분. 끝나면 서비스 화면 위쪽의 `https://navigator-demo-....onrender.com` 이 시연 주소.
5. 열어서 아이디 `navigator` / 넣은 비밀번호로 들어가지는지 확인 → 주소와 비밀번호를 전달.

- 비밀번호 변경: 서비스 → Environment → `SITE_PASSWORD` 수정 → 저장(자동 재시작).
- 코드 반영: 자동 배포는 꺼 두었다. 서비스 → **Manual Deploy → Deploy latest commit**.
- 시연 전날 한 번 열어 두면 첫 접속 대기를 피할 수 있다.
- 30일 뒤 DB 가 만료되면 Blueprint 를 다시 적용한다. 시작할 때마다 가상 데이터가 다시 채워진다.

## B. 맥북 + 임시 주소

운영 중인 `:8000` 은 그대로 두고, 가상 데이터용 DB `navigator_demo` 를 따로 만들어 `:8100` 에 띄운다.

```bash
brew install cloudflared                       # 처음 한 번
cd ~/navigator && git pull
SITE_PASSWORD=비밀번호 ./deploy/mac_demo.sh
```

마지막에 나오는 `https://....trycloudflare.com` 이 시연 주소. 창을 닫거나 Ctrl+C 하면 주소도 닫힌다.

## 다른 서버에 올릴 때

저장소 루트의 `Dockerfile` 로 이미지를 만든다. 필요한 값은 `DATABASE_URL`(PostgreSQL 16 + pgvector), `SITE_PASSWORD`, `PORT`.
시작할 때 스키마 → 가상 데이터 → 벡터 생성 → 서버 순으로 돈다(`deploy/demo_start.sh`).
