"""API 와 빌드된 화면(frontend/dist)을 한 주소에서 함께 서빙.

  uvicorn app.site:site --port 8000   ->  http://127.0.0.1:8000/navigator

/api/* 는 API(app.main), 나머지는 화면. 화면 경로(/navigator 등)는 index.html 로 돌려 준다.
화면을 고쳤으면 `cd frontend && npm run build` 후 재시작.

SITE_PASSWORD 를 넣으면 주소 전체에 기본 인증(아이디 SITE_USER, 기본 navigator)을 건다.
외부에 시연 주소를 열 때 쓴다 (docs/demo_link.md). /api/health 는 호스팅 상태 확인용으로 열어 둔다.
"""
import base64
import os
import secrets
from pathlib import Path

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from app.main import app, lifespan

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


class _SPA(StaticFiles):
    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as e:
            if e.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


class _BasicAuth:
    OPEN = {"/api/health"}

    def __init__(self, app, user: str, password: str):
        self.app = app
        self.expected = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in self.OPEN:
            return await self.app(scope, receive, send)
        got = dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")
        if secrets.compare_digest(got.encode(), self.expected.encode()):
            return await self.app(scope, receive, send)
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"www-authenticate", b'Basic realm="Navigator", charset="UTF-8"'),
                                (b"content-type", b"text/plain; charset=utf-8")]})
        await send({"type": "http.response.body", "body": "아이디와 비밀번호가 필요합니다.".encode()})


site = Starlette(routes=[Mount("/api", app=app), Mount("/", app=_SPA(directory=DIST, html=True))],
                 lifespan=lambda _: lifespan(app))
if os.environ.get("SITE_PASSWORD"):
    site.add_middleware(_BasicAuth, user=os.environ.get("SITE_USER", "navigator"),
                        password=os.environ["SITE_PASSWORD"])
