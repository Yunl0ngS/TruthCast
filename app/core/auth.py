"""
API Key 认证依赖 — 从环境变量读取预期密钥，未配置时自动跳过（向下兼容）。
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.core.logger import get_logger

logger = get_logger("truthcast.auth")

_bearer_scheme = HTTPBearer(auto_error=False)
_apikey_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# 不需要认证的路径前缀
_PUBLIC_PATHS: set[str] = {"/health", "/docs", "/redoc", "/openapi.json"}


def _get_expected_key() -> Optional[str]:
    """读取 TRUTHCAST_API_KEY，空字符串视为未配置。"""
    key = os.getenv("TRUTHCAST_API_KEY", "").strip()
    return key or None


async def require_api_key(
    request: Request,
    bearer: Optional[HTTPAuthorizationCredentials] = Security(_bearer_scheme),
    x_api_key: Optional[str] = Security(_apikey_header),
) -> Optional[str]:
    """
    FastAPI 依赖：验证请求携带的 API Key。

    - 若 ``TRUTHCAST_API_KEY`` 未设置 → 认证关闭，所有请求放行。
    - 若已设置 → 要求 ``Authorization: Bearer <key>`` 或 ``X-API-Key: <key>``。
    - ``/health``、``/docs``、``/redoc``、``/openapi.json`` 始终免认证。
    """
    expected = _get_expected_key()

    # 未配置密钥 → 跳过认证
    if expected is None:
        return None

    # 公开路径放行
    if request.url.path in _PUBLIC_PATHS:
        return None

    # 优先 Bearer，其次 X-API-Key
    provided: Optional[str] = None
    if bearer and bearer.credentials:
        provided = bearer.credentials
    elif x_api_key:
        provided = x_api_key.strip()

    if not provided:
        logger.warning("认证失败：缺少 API Key (path=%s)", request.url.path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 API Key，请通过 Authorization: Bearer <key> 或 X-API-Key 请求头提供",
        )

    if provided != expected:
        logger.warning("认证失败：无效的 API Key (path=%s)", request.url.path)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无效的 API Key",
        )

    return provided
