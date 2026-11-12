"""API 와 빌드된 화면(frontend/dist)을 한 주소에서 함께 서빙.

  uvicorn app.site:site --port 8000   ->  http://127.0.0.1:8000/navigator

/api/* 는 API(app.main), 나머지는 화면. 화면 경로(/navigator 등)는 index.html 로 돌려 준다.
화면을 고쳤으면 `cd frontend && npm run build` 후 재시작.
"""
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


site = Starlette(routes=[Mount("/api", app=app), Mount("/", app=_SPA(directory=DIST, html=True))],
                 lifespan=lambda _: lifespan(app))
