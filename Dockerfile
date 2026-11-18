# 시연 주소용 이미지: 화면 빌드 + API 를 한 주소(:$PORT)에서 서빙. 설정은 docs/demo_link.md
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/pyproject.toml backend/
COPY backend/app backend/app
RUN pip install --no-cache-dir ./backend
COPY db db
COPY seeds seeds
COPY scripts scripts
COPY deploy/demo_start.sh deploy/
COPY --from=web /web/dist frontend/dist
ENV EMBEDDER=hash MAILER=mock NAVIGATOR_DEV_EXPOSE_LINK=true COLLECT_AUTO_MINUTES=0 PORT=8000
CMD ["./deploy/demo_start.sh"]
