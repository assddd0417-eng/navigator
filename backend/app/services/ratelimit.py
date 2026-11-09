"""공개 API IP별 분당 호출 제한. 프로세스 메모리 기준이라 다중 인스턴스면 Redis 로 옮겨야 함."""
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
    limiter.check(f"nav:{client_key(request)}", get_settings().navigator_rate_limit_per_minute)
