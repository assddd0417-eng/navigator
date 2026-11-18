# 내부망 서버 설치 안내

국기원 내부망 서버에 Navigator 를 깔고 실데이터로 시험 운영하는 절차. Ubuntu 24.04 기준으로 적고, Rocky/RHEL 계열은 다른 부분만 따로 적는다.

```
브라우저 ──► nginx :80 ──► uvicorn 127.0.0.1:8000 (API /api/* + 화면) ──► PostgreSQL 16 + pgvector
             └ 담당자 화면·API 는 아이디/비밀번호 확인
```

- 기업: 로그인 없음. 사업자번호로 조회하고, 회사 정보 화면은 등록 이메일로 받은 6자리 확인 코드로 연다.
- 기관 담당자: `/login` 에서 계정을 골라 들어간다. 앱 안에는 비밀번호가 없으므로 nginx 비밀번호로 막는다 ([6. 접속 제한](#6-접속-제한과-담당자-비밀번호)).

## 1. 필요 환경

| 항목 | 내용 |
|------|------|
| OS | Ubuntu 22.04/24.04 또는 Rocky/RHEL 9 (64비트) |
| CPU·메모리 | 기본(`EMBEDDER=hash`) 2코어·4GB. BGE-M3 사용 시 4코어·16GB 권장 (GPU 없어도 됨) |
| 디스크 | 20GB 이상 (BGE-M3 모델 2.3GB, PyTorch 약 1GB 포함) |
| PostgreSQL | 16, 확장 `vector`(pgvector 0.6 이상)·`pg_trgm` |
| Python | 3.11 이상 |
| Node.js | 화면 빌드에만 필요 (20 이상). 인터넷 PC 에서 빌드해 `dist/` 만 옮겨도 된다 |
| nginx | 접속 제한·업로드 크기 설정용 |
| 메일 | 기관 SMTP 릴레이 (기업 확인 코드·공고 알림·참여 권유 발송) |
| 네트워크 | 인터넷 불필요. 국기원 공지사항 자동 수집을 쓸 때만 `www.krit.re.kr` 로 나갈 수 있어야 함 |

## 2. 반입물 준비 (서버가 인터넷에 못 나갈 때)

서버에서 바로 `pip`·`npm` 이 되면 이 단계는 건너뛴다. 인터넷 PC 는 서버와 같은 OS·Python 버전이어야 한다.

```bash
git clone https://github.com/assddd0417-eng/navigator.git && cd navigator

# 화면 빌드 (가상 기업 버튼 숨김)
(cd frontend && npm ci && VITE_HIDE_DEMO=true npm run build)        # → frontend/dist/

# 파이썬 패키지
python3 -m venv /tmp/wv && /tmp/wv/bin/pip wheel -w wheels ./backend
#   BGE-M3 를 쓰면 (CPU 전용 PyTorch):
#   /tmp/wv/bin/pip wheel -w wheels './backend[bge]' --extra-index-url https://download.pytorch.org/whl/cpu

# BGE-M3 모델 (쓸 때만)
/tmp/wv/bin/pip install huggingface_hub
/tmp/wv/bin/hf download BAAI/bge-m3 --local-dir models/bge-m3       # 구버전은 huggingface-cli download

tar czf navigator-bundle.tgz navigator/        # 저장소 폴더째 (frontend/dist, wheels, models 포함)
```

## 3. 설치

### 3-1. 패키지와 실행 계정

```bash
sudo apt install -y postgresql-16 postgresql-16-pgvector python3-venv nginx apache2-utils
sudo useradd -r -m -d /opt/navigator -s /usr/sbin/nologin navigator
sudo -u navigator git clone https://github.com/assddd0417-eng/navigator.git /opt/navigator
#   반입했으면: sudo tar xzf navigator-bundle.tgz -C /opt && sudo chown -R navigator: /opt/navigator
```

- Ubuntu 22.04 는 기본 저장소에 PostgreSQL 16 이 없어 PGDG 저장소(apt.postgresql.org)를 먼저 추가한다.
- Rocky/RHEL 9: PGDG 저장소 추가 후 `dnf install postgresql16-server pgvector_16 python3.11 nginx httpd-tools`, `postgresql-16-setup initdb`. SELinux 가 켜져 있으면 `setsebool -P httpd_can_network_connect 1` (nginx → 8000 연결).

### 3-2. DB 와 마이그레이션

확장은 슈퍼유저만 만들 수 있어 `postgres` 계정으로 먼저 만든다.

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE navigator LOGIN PASSWORD '<DB 비밀번호>';
CREATE DATABASE navigator OWNER navigator ENCODING 'UTF8' TEMPLATE template0;
\c navigator
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
SQL

cd /opt/navigator
export DATABASE_URL='postgresql://navigator:<DB 비밀번호>@127.0.0.1:5432/navigator'
./scripts/migrate.sh                                                   # "적용: 0001_schema.sql" → "완료"
psql "$DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -f seeds/base.sql      # 담당자 계정·사업 코드
```

`seeds/navigator_*.sql`(가상 기업·공고)은 넣지 않는다. 넣었다면 [7-1](#7-1-가상-데이터-지우기)로 지운다.

### 3-3. 백엔드

```bash
cd /opt/navigator/backend
sudo -u navigator python3 -m venv .venv
sudo -u navigator .venv/bin/pip install -e .                 # BGE-M3: -e ".[bge]"
#   반입했으면: .venv/bin/pip install --no-index --find-links ../wheels navigator-backend   (BGE-M3: 'navigator-backend[bge]')
sudo -u navigator cp .env.example .env && sudo chmod 600 .env
```

화면은 `/opt/navigator/frontend/dist` 를 그대로 쓴다. 서버에서 빌드하면 `cd frontend && npm ci && VITE_HIDE_DEMO=true npm run build`.

### 3-4. `.env` 설정 (`backend/.env`)

꼭 바꿀 것:

| 항목 | 값 | 설명 |
|------|----|------|
| `DATABASE_URL` | `postgresql://navigator:<비밀번호>@127.0.0.1:5432/navigator` | |
| `NAVIGATOR_PUBLIC_BASE_URL` | `http://<서버 주소>` | 메일 속 링크(관리 링크·수신 확인·수신 거부)가 이 주소로 나간다 |
| `MAILER` | `smtp` | `mock` 이면 메일을 보내지 않아 기업이 확인 코드를 못 받는다 |
| `SMTP_HOST` / `SMTP_PORT` | 기관 메일 릴레이 | |
| `SMTP_SECURITY` | `starttls`(587) / `ssl`(465) / `none`(내부 릴레이 25) | |
| `SMTP_USER` / `SMTP_PASSWORD` | 인증 계정 | 릴레이가 인증 없이 받으면 둘 다 비운다 |
| `SMTP_FROM` / `SMTP_FROM_NAME` | 보내는 주소·이름 | `SMTP_FROM` 을 비우면 `SMTP_USER` |
| `REQUIREMENT_EXTRACTOR` | `rules` | 공고 조건 뽑기를 규칙으로만 (외부 LLM 호출 없음) |

임베딩 (택1):

| 방식 | 설정 | 비고 |
|------|------|------|
| 기본 | `EMBEDDER=hash` | 모델 없이 바로 동작. 관련도 정확도는 낮다 |
| 권장 | `EMBEDDER=bge_m3`, `EMBEDDING_MODEL_PATH=/opt/navigator/models/bge-m3`, `EMBEDDING_OFFLINE=true`, `EMBEDDING_DEVICE=cpu` | 검증 결과는 BGE-M3 기준 ([navigator_eval.md](navigator_eval.md)). 메모리가 부족하면 `EMBEDDING_BATCH_SIZE=4` |

임베딩 방식을 바꾸면 서버를 다시 띄운 뒤 `cd backend && .venv/bin/python -m app.reembed` 로 다시 계산한다 (`/api/health` 의 `reindex_needed` 가 `false` 가 될 때까지).

그 밖의 항목은 기본값 그대로 둔다. `NAVIGATOR_DEV_EXPOSE_LINK` 는 켜지 않는다 (켜면 확인 코드가 화면에 그대로 보인다).

## 4. 실행과 자동 시작

먼저 손으로 띄워 확인한다.

```bash
cd /opt/navigator/backend
sudo -u navigator .venv/bin/uvicorn app.site:site --host 127.0.0.1 --port 8000
curl -s 127.0.0.1:8000/api/health        # "status":"ok", "schema_version":"0001"
```

확인되면 Ctrl+C 로 끄고 systemd 에 등록한다 ([deploy/navigator.service](../deploy/navigator.service)).

```bash
sudo cp /opt/navigator/deploy/navigator.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now navigator
systemctl status navigator               # active (running)
journalctl -u navigator -f               # 로그
```

서버를 재부팅해도 PostgreSQL → Navigator 순서로 자동으로 뜬다. `--proxy-headers` 는 nginx 뒤에서 기업별 요청 제한(IP당 분당 60회)이 실제 접속 IP 로 계산되게 한다.

## 5. nginx

```bash
sudo cp /opt/navigator/deploy/nginx-navigator.conf /etc/nginx/conf.d/navigator.conf
sudo rm -f /etc/nginx/sites-enabled/default           # Ubuntu 기본 사이트를 끈다
sudo nginx -t && sudo systemctl reload nginx
```

- 업로드 상한 35MB, 응답 대기 300초로 잡아 두었다.
- HTTPS 를 쓰면 기관 인증서로 `listen 443 ssl` 블록을 추가하고 `NAVIGATOR_PUBLIC_BASE_URL` 도 `https://` 로 바꾼다.
- 방화벽은 80(또는 443)만 연다. 8000·5432 는 열지 않는다.

## 6. 접속 제한과 담당자 비밀번호

Navigator 담당자 로그인은 계정을 고르는 방식이라 앱 안에 비밀번호가 없다. 내부망이라도 누구나 담당자 화면에 들어올 수 있으므로 nginx 에서 아이디/비밀번호를 묻는다.

| 주소 | 비밀번호 |
|------|----------|
| `/navigator`, 기업용 API | 없음 |
| `/login`, `/staff/*` | 필요 |
| 담당자 API (`X-User-Id` 헤더가 붙은 `/api/*` 요청) | 필요 |

```bash
sudo htpasswd -c /etc/nginx/navigator.htpasswd <담당자 아이디>     # 처음 한 번 (-c 는 파일을 새로 만든다)
sudo htpasswd /etc/nginx/navigator.htpasswd <다른 담당자 아이디>   # 담당자 추가
sudo htpasswd /etc/nginx/navigator.htpasswd <아이디>               # 비밀번호 변경 (같은 명령으로 덮어씀)
sudo htpasswd -D /etc/nginx/navigator.htpasswd <아이디>            # 삭제
sudo chown root:www-data /etc/nginx/navigator.htpasswd && sudo chmod 640 /etc/nginx/navigator.htpasswd
#   Rocky/RHEL 은 www-data 대신 nginx
```

설치할 때 정한 첫 비밀번호는 담당자에게 전달하고, 담당자가 정한 비밀번호로 위 '비밀번호 변경' 명령을 다시 실행한다. 비밀번호 파일은 nginx 재시작 없이 바로 적용된다.

- 브라우저가 처음 `/login` 에 들어갈 때 아이디/비밀번호 창을 띄운다. 그다음 '시작하기'로 들어간다.
- 앱 안에서는 담당자가 모두 1번 계정(공고담당)으로 기록된다. 이름·부서 표시는 바꿀 수 있다.

```sql
-- psql "$DATABASE_URL"
UPDATE ax.department SET name = '<부서명>' WHERE id = 1;
UPDATE ax.app_user   SET name = '<표시 이름>' WHERE id = 1;   -- 로그인 뒤 상단에 나오는 이름
```

로그인 화면 카드의 '공고담당 · 사업지원팀' 글자는 화면에 고정돼 있어 그대로 나온다.

## 7. 데이터

### 7-1. 가상 데이터 지우기

3-2 대로 가상 시드를 넣지 않았다면 할 일이 없다. 시연용으로 넣었거나 `scripts/smoke_test.sh` 를 돌렸다면 실데이터를 넣기 전에 비운다.

```bash
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -v confirm=yes -f scripts/clear_demo_data.sql
```

- 지움: 기업 전체, 공고 전체(원문·첨부 포함), 매칭·추천·알림·권유 기록, 외부 수집 기록, 이름에 `(가상)` 이 붙은 사업.
- 남김: 담당자 계정, 코드표, 사업 코드, 외부 출처 설정, 감사 로그. 2번 열람자 계정은 끈다.
- 실데이터가 들어간 뒤에는 돌리지 않는다. `-v confirm=yes` 가 없으면 아무것도 하지 않는다.

새로 설치했어도 아래는 꼭 한다. 연결되지 않은 외부 수집 출처를 끈다. 켜 두면 담당자 화면 '외부 수집'의 '지금 수집'이 가상 공고·가상 특허를 넣는다.

```sql
UPDATE ax.external_source SET is_active = false WHERE code IN ('NTS_BIZ', 'KIPRIS', 'DART', 'BIZINFO', 'KRIT');
```

`scripts/smoke_test.sh` 는 운영 DB 에 돌리지 않는다 (시험 공고를 만든다).

### 7-2. 실데이터 넣기

**공고** (담당자 화면 `/staff/announcements`)

1. '직접 등록'에서 제목과 공고문 글자(한글 파일에서 전체 선택·복사)를 붙여 넣는다 → 작성중 공고가 생긴다.
2. '조건 뽑기'로 기업규모·휴폐업·결격사유·지원 한도 등 후보를 받는다 (규칙 기반, 외부 전송 없음).
3. 원문과 대조해 고치고 '확인하고 공개'. 공개된 공고만 기업 추천·알림·매칭에 쓰인다.

공고문 PDF 는 화면에 올리는 버튼이 없어 API 로 올린다. 올린 뒤 1번 화면 목록에 작성중으로 나온다. 스캔본 PDF 는 글자를 못 읽는다.

```bash
curl -u <담당자 아이디> -H 'X-User-Id: 1' http://<서버>/api/navigator/announcements/upload \
  -F file=@공고문.pdf -F announcement_no=<공고번호> -F agency_name=국방기술진흥연구소 -F title='<공고 제목>' \
  -F receipt_start=2026-12-01 -F receipt_end=2026-12-31
```

**기업**

- 기업이 직접 `/navigator/register` 에서 등록한다 (사업자번호, 상호, 대표자명, 개업일, 이메일 필수). 국세청 진위확인이 연동 전이라 '미확인'으로 저장된다.
- 이후 회사 정보 화면(이메일 확인 코드)에서 신용등급·인증·특허·R&D 이력·제품·보유 기술을 입력하고, 확인서 PDF 를 올려 값을 채울 수 있다.
- 시험 기업이 많아 담당자가 대신 등록해야 하면, 담당자가 기업 이메일로 등록하고 확인 코드는 기업이 받는다. 담당자 화면에 기업 일괄 등록 기능은 없다.

**매칭**: `/staff/navigator` 에서 공고를 고르면 조건을 충족하는 기업이 관련도 순으로 나온다. 참여 권유 메일은 '권유 메일 받기'에 동의한 기업에만 간다.

## 8. 외부 연동

PoC 에서는 아래를 연결하지 않았다. 모두 **연동 예정**이다.

| 출처 | 쓰임 | 현재 |
|------|------|------|
| 국세청 사업자 진위확인·상태조회 | 등록 시 확인, 휴·폐업 | 연동 예정 (등록은 '미확인'으로 저장) |
| KIPRIS Plus | 특허 | 연동 예정 (기업 자가입력) |
| OpenDART | 매출·직원 수 | 연동 예정 (기업 자가입력) |
| 기업마당 | 지원사업 공고 | 연동 예정 (담당자 등록) |
| NICE·KED 신용등급 | 신용등급 | 연동 예정 (확인서 업로드·자가입력) |
| 확인서 OCR | 스캔본 확인서 | 연동 예정 (글자가 있는 PDF 만 읽음) |

국기원 공지사항 수집(`KRIT`)은 키 없이 게시판을 읽는 방식이라, 서버가 `www.krit.re.kr` 에 나갈 수 있으면 쓸 수 있다.

```bash
psql "$DATABASE_URL" -c "UPDATE ax.external_source SET is_active = true WHERE code = 'KRIT'"
# backend/.env 에 SOURCE_KRIT=live 추가 후 sudo systemctl restart navigator
# 하루 한 번 (crontab -u navigator -e)
0 6 * * * cd /opt/navigator/backend && .venv/bin/python -m app.collect --source KRIT >> /var/log/navigator-collect.log 2>&1
```

받은 공고는 작성중으로 들어오고, 7-2 의 2~3 단계를 거쳐야 공개된다.

## 9. 설치 확인

| 확인 | 기대 |
|------|------|
| `curl -s http://<서버>/api/health` | `status: ok`, `schema_version: 0001`, `reindex_needed: false`, `requirement_extractor.mode: rules` |
| `http://<서버>/navigator` | 비밀번호 없이 열림. '시연용 기업' 버튼이 없음 |
| `http://<서버>/login` | 아이디/비밀번호 창 → '시작하기' → 공고별 적합 기업 |
| 공고 1건 등록 → 조건 뽑기 → 확인하고 공개 | 기업 화면 공고 목록에 보임 |
| 시험 기업 등록 → '회사 정보 입력·수정' | 등록 이메일로 6자리 코드 도착 |
| `/staff/navigator` 에서 그 공고 선택 | 시험 기업이 판정과 함께 나옴 |

## 10. 업데이트·백업

```bash
# 업데이트
cd /opt/navigator && sudo -u navigator git pull
sudo -u navigator backend/.venv/bin/pip install -q -e backend
(cd frontend && sudo -u navigator npm ci && sudo -u navigator env VITE_HIDE_DEMO=true npm run build)
DATABASE_URL=... ./scripts/migrate.sh          # 새 마이그레이션만 적용, 적용된 파일이 바뀌었으면 멈춤
sudo systemctl restart navigator

# 백업 (매일, root crontab)
0 2 * * * sudo -u postgres pg_dump -Fc navigator > /var/backups/navigator-$(date +\%a).dump
# 복원: sudo -u postgres pg_restore -c -d navigator /var/backups/navigator-Mon.dump
```

## 11. 알아 둘 점

- 담당자 구분: 앱 안에서는 모든 담당자가 1번 계정으로 기록된다. 누가 했는지는 nginx 접속 로그(`/var/log/nginx/access.log` 의 아이디)로 본다.
- 요청 제한은 서버 메모리 기준이라 서버를 한 대만 띄운다 (uvicorn `--workers` 를 늘리지 않는다).
- 같은 DB 에 `EMBEDDER` 가 다른 서버 두 개를 띄우지 않는다.
- 공고문·확인서 원본 파일은 저장하지 않고 뽑은 글자만 DB 에 둔다.
