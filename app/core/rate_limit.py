"""
IP 限流中间件 — 基于滑动窗口的请求频率控制。

使用内存字典按客户端 IP 记录请求时间戳，超限时返回 429。
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from threading import Lock

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from app.core.logger import get_logger

logger = get_logger("truthcast.rate_limit")

# 不受限流约束的路径前缀
_EXEMPT_PATHS: set[str] = {"/health", "/docs", "/redoc", "/openapi.json"}


def _get_rpm() -> int:
    """每分钟最大请求数，0 表示不限流。"""
    try:
        return int(os.getenv("TRUTHCAST_RATE_LIMIT_RPM", "60"))
    except (TypeError, ValueError):
        return 60


class RateLimitMiddleware(BaseHTTPMiddleware):
    """基于客户端 IP 的滑动窗口限流中间件。"""

    def __init__(self, app, **kwargs):  # noqa: ANN001
        super().__init__(app, **kwargs)
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    @staticmethod
    def _client_ip(request: Request) -> str:
        """提取客户端 IP（优先 X-Forwarded-For）。"""
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        rpm = _get_rpm()

        # 限流关闭
        if rpm <= 0:
            return await call_next(request)

        # 豁免路径
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        ip = self._client_ip(request)
        now = time.monotonic()
        window = 60.0  # 1 分钟窗口

        with self._lock:
            timestamps = self._buckets[ip]
            # 清除过期记录
            cutoff = now - window
            self._buckets[ip] = timestamps = [t for t in timestamps if t > cutoff]

            if len(timestamps) >= rpm:
                retry_after = int(timestamps[0] + window - now) + 1
                logger.warning(
                    "限流触发：ip=%s, rpm=%d, retry_after=%ds",
                    ip,
                    rpm,
                    retry_after,
                )
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"请求过于频繁，请 {retry_after} 秒后重试"},
                    headers={"Retry-After": str(retry_after)},
                )

            timestamps.append(now)

        response = await call_next(request)
        # 添加限流信息到响应头（便于客户端感知）
        response.headers["X-RateLimit-Limit"] = str(rpm)
        with self._lock:
            remaining = max(0, rpm - len(self._buckets.get(ip, [])))
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
