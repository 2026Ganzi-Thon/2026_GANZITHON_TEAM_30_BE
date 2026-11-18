import threading
import time
from collections import deque

from fastapi import Depends, HTTPException, Request, status

from app import config
from app.deps import get_current_user
from app.models import User


class RateLimiter:
    def __init__(self, enabled: bool):
        self.enabled = enabled
        self._hits: dict[str, tuple[deque, float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: float) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        with self._lock:
            hits, _ = self._hits.setdefault(key, (deque(), window))
            while hits and hits[0] <= now - window:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = int(window - (now - hits[0])) + 1
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    f"요청이 너무 많아요. {retry_after}초 뒤에 다시 시도해 주세요",
                    headers={"Retry-After": str(retry_after)},
                )
            hits.append(now)
            if len(self._hits) > 20000:
                self._purge(now)

    def _purge(self, now: float) -> None:
        expired = [k for k, (hits, window) in self._hits.items() if not hits or hits[-1] <= now - window]
        for k in expired:
            del self._hits[k]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter(config.RATE_LIMIT_ENABLED)


def client_ip(request: Request) -> str:
    if config.TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def limit_ip(name: str, limit: int, window: float):
    def dependency(request: Request) -> None:
        limiter.hit(f"{name}:ip:{client_ip(request)}", limit, window)

    return Depends(dependency)


def limit_user(name: str, limit: int, window: float):
    def dependency(me: User = Depends(get_current_user)) -> None:
        limiter.hit(f"{name}:user:{me.id}", limit, window)

    return Depends(dependency)
