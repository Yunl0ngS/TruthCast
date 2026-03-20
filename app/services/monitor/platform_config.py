from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MonitorPlatformConfig:
    key: str
    display_name: str
    newsnow_id: str
    enabled: bool = True
    scan_interval_minutes: int | None = None


DEFAULT_MONITOR_PLATFORMS = [
    MonitorPlatformConfig("thepaper", "澎湃新闻", "thepaper", True, 10),
    MonitorPlatformConfig("ifeng", "凤凰网", "ifeng", True, 10),
    MonitorPlatformConfig("cankaoxiaoxi", "参考消息", "cankaoxiaoxi", True, 20),
    MonitorPlatformConfig("wallstreetcn-hot", "华尔街见闻", "wallstreetcn-hot", True, 15),
    MonitorPlatformConfig("wallstreetcn-quick", "华尔街见闻", "wallstreetcn-quick", True, 5),
    MonitorPlatformConfig("tencent-hot", "腾讯新闻", "tencent-hot", True, 20),
    MonitorPlatformConfig("zaobao", "联合早报", "zaobao", True, 30),
    MonitorPlatformConfig("cls-hot", "财联社", "cls-hot", True, 10),
    MonitorPlatformConfig("cls-telegraph", "财联社", "cls-telegraph", True, 5),
    MonitorPlatformConfig("weibo", "微博", "weibo", False, 5),
    MonitorPlatformConfig("zhihu", "知乎", "zhihu", False, 10),
    MonitorPlatformConfig("douyin", "抖音", "douyin", False, 10),
    MonitorPlatformConfig("bilibili", "B站", "bilibili-hot-search", False, 15),
    MonitorPlatformConfig("kuaishou", "快手", "kuaishou", False, 15),
    MonitorPlatformConfig("tieba", "百度贴吧", "tieba", False, 15),
    MonitorPlatformConfig("36kr", "36氪", "36kr-quick", False, 20),
    MonitorPlatformConfig("ithome", "IT之家", "ithome", False, 20),
    MonitorPlatformConfig("juejin", "掘金", "juejin", False, 20),
    MonitorPlatformConfig("sspai", "少数派", "sspai", False, 20),
    MonitorPlatformConfig("v2ex", "V2EX", "v2ex-share", False, 20),
    MonitorPlatformConfig("github", "GitHub", "github-trending-today", False, 30),
]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_config_path() -> Path:
    return _project_root() / "config" / "monitor_platforms.yaml"


def _parse_platform_record(item: dict[str, Any]) -> MonitorPlatformConfig | None:
    key = str(item.get("key", "")).strip().lower()
    if not key:
        return None
    display_name = str(item.get("display_name") or item.get("name") or key).strip()
    newsnow_id = str(item.get("newsnow_id") or item.get("platform_id") or key).strip()
    enabled = bool(item.get("enabled", True))
    interval = item.get("scan_interval_minutes")
    try:
        scan_interval_minutes = max(1, int(interval)) if interval is not None else None
    except (TypeError, ValueError):
        scan_interval_minutes = None
    return MonitorPlatformConfig(
        key=key,
        display_name=display_name,
        newsnow_id=newsnow_id,
        enabled=enabled,
        scan_interval_minutes=scan_interval_minutes,
    )


def _load_from_yaml(config_path: Path) -> list[MonitorPlatformConfig]:
    if not config_path.exists():
        return list(DEFAULT_MONITOR_PLATFORMS)

    with config_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    items = data.get("platforms", [])
    if not isinstance(items, list):
        logger.warning("监测平台配置格式错误：platforms 不是数组，回退默认配置")
        return list(DEFAULT_MONITOR_PLATFORMS)

    parsed = [_parse_platform_record(item) for item in items if isinstance(item, dict)]
    result = [item for item in parsed if item is not None]
    return result or list(DEFAULT_MONITOR_PLATFORMS)


def _enabled_platform_override() -> set[str] | None:
    raw = os.getenv("TRUTHCAST_MONITOR_ENABLED_PLATFORMS", "").strip()
    if not raw:
        return None
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _json_override_map(env_name: str) -> dict[str, Any]:
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("%s 不是合法 JSON，忽略覆盖配置", env_name)
        return {}
    if not isinstance(parsed, dict):
        logger.warning("%s 不是对象，忽略覆盖配置", env_name)
        return {}
    return {str(key).lower(): value for key, value in parsed.items()}


def load_monitor_platforms(config_path: str | None = None) -> list[MonitorPlatformConfig]:
    path = Path(config_path or os.getenv("TRUTHCAST_MONITOR_PLATFORM_CONFIG", "") or _default_config_path())
    items = _load_from_yaml(path)

    enabled_override = _enabled_platform_override()
    newsnow_id_override = _json_override_map("TRUTHCAST_NEWSNOW_PLATFORM_IDS")
    interval_override = _json_override_map("TRUTHCAST_MONITOR_PLATFORM_INTERVALS")

    result: list[MonitorPlatformConfig] = []
    for item in items:
        enabled = item.enabled if enabled_override is None else item.key in enabled_override
        newsnow_id = str(newsnow_id_override.get(item.key, item.newsnow_id))
        interval_raw = interval_override.get(item.key, item.scan_interval_minutes)
        try:
            scan_interval_minutes = max(1, int(interval_raw)) if interval_raw is not None else None
        except (TypeError, ValueError):
            scan_interval_minutes = item.scan_interval_minutes
        result.append(
            MonitorPlatformConfig(
                key=item.key,
                display_name=item.display_name,
                newsnow_id=newsnow_id,
                enabled=enabled,
                scan_interval_minutes=scan_interval_minutes,
            )
        )
    return result


def load_enabled_monitor_platforms(config_path: str | None = None) -> list[MonitorPlatformConfig]:
    return [item for item in load_monitor_platforms(config_path) if item.enabled]
