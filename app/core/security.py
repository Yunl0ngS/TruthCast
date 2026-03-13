"""
SSRF 防护工具 — 验证用户提供的 URL 是否安全可请求。

阻止对私有 / 内部网段、链路本地地址以及云元数据端点的请求。
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse

from app.core.logger import get_logger

logger = get_logger("truthcast.security")

_ALLOWED_SCHEMES = {"http", "https"}

# 云厂商元数据 IP（AWS / GCP / Azure 等）
_METADATA_IPS = {
    "169.254.169.254",
    "metadata.google.internal",
}


class SSRFBlockedError(Exception):
    """URL 被 SSRF 策略拦截。"""


def _is_private_ip(ip_str: str) -> bool:
    """判断 IP 地址是否属于私有 / 保留网段。"""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # 无法解析一律视为危险

    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def validate_url_for_ssrf(url: str) -> str:
    """
    验证并返回安全的 URL。

    检查项:
    1. scheme 必须为 http / https
    2. hostname 不能为空
    3. DNS 解析后的 IP 不属于私有 / 内部 / 元数据网段

    当 ``TRUTHCAST_SSRF_BLOCK_PRIVATE`` 为 ``false`` 时跳过私有 IP 检查
    （仅建议在受信任的内部网络环境下使用）。

    Raises
    ------
    SSRFBlockedError
        URL 不符合安全策略时抛出。
    """
    block_private = os.getenv(
        "TRUTHCAST_SSRF_BLOCK_PRIVATE", "true"
    ).strip().lower() not in (
        "false",
        "0",
        "no",
    )

    # --- 1. scheme ---
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise SSRFBlockedError(
            f"不允许的 URL 协议：{parsed.scheme!r}，仅支持 http/https"
        )

    # --- 2. hostname ---
    hostname = parsed.hostname
    if not hostname:
        raise SSRFBlockedError("URL 中缺少有效的主机名")

    # --- 3. 元数据端点（始终阻止） ---
    if hostname in _METADATA_IPS:
        raise SSRFBlockedError(f"禁止访问云元数据端点：{hostname}")

    if not block_private:
        return url

    # --- 4. DNS 解析 + 私有 IP 检查 ---
    try:
        addrinfos = socket.getaddrinfo(
            hostname, parsed.port or 443, proto=socket.IPPROTO_TCP
        )
    except socket.gaierror as exc:
        raise SSRFBlockedError(f"DNS 解析失败：{hostname} ({exc})") from exc

    for family, _type, _proto, _canonname, sockaddr in addrinfos:
        ip_str = sockaddr[0]
        if ip_str in _METADATA_IPS or _is_private_ip(ip_str):
            raise SSRFBlockedError(f"URL 解析到内部/私有地址：{hostname} -> {ip_str}")

    return url
