"""로그인 없는 공개 API 의 조회 횟수 제한 (같은 곳에서 오는 요청, 1분 창).

PoC 는 프로세스 메모리에 둔다. 서버를 여러 대로 늘리면 Redis 등 공유 저장소로 옮긴다.
"""
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.config import get_settings


class RateLimiter:
    def __init__(self, window_s: float = 60.0):
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int) -> None:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > self.window_s:
            q.popleft()
        if len(q) >= limit:
            retry = int(self.window_s - (now - q[0])) + 1
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                "요청이 너무 많습니다. 잠시 후 다시 시도하세요",
                                headers={"Retry-After": str(retry)})
        q.append(now)

    def reset(self) -> None:
        self._hits.clear()


limiter = RateLimiter()


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def public_rate_limit(request: Request) -> None:
    """공개(로그인 없는) Navigator API 의존성."""
    limiter.check(f"nav:{client_key(request)}", get_settings().navigator_rate_limit_per_minute)
