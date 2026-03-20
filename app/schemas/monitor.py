from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SubscriptionType(str, Enum):
    KEYWORD = "keyword"
    TOPIC = "topic"


class TriggerMode(str, Enum):
    THRESHOLD = "threshold"
    HIT = "hit"
    SMART = "smart"


class NotifyChannel(str, Enum):
    WEBHOOK = "webhook"
    WECOM = "wecom"
    DINGTALK = "dingtalk"
    FEISHU = "feishu"
    EMAIL = "email"


class TrendDirection(str, Enum):
    RISING = "rising"
    STABLE = "stable"
    FALLING = "falling"
    NEW = "new"


class AlertStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    IGNORED = "ignored"


class SubscriptionBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: SubscriptionType
    keywords: list[str] = Field(default_factory=list)
    match_mode: str = Field(default="any", pattern="^(any|all|regex)$")
    platforms: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    trigger_mode: TriggerMode = Field(default=TriggerMode.THRESHOLD)
    risk_threshold: int = Field(default=70, ge=0, le=100)
    smart_threshold: dict[str, Any] = Field(default_factory=dict)
    notify_channels: list[NotifyChannel] = Field(default_factory=list)
    notify_config: dict[str, Any] = Field(default_factory=dict)
    notify_template: str | None = Field(default=None)
    quiet_hours: dict[str, Any] | None = Field(default=None)
    is_active: bool = Field(default=True)
    priority: int = Field(default=0)


class SubscriptionCreate(SubscriptionBase):
    pass


class SubscriptionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    keywords: list[str] | None = None
    match_mode: str | None = Field(default=None, pattern="^(any|all|regex)$")
    platforms: list[str] | None = None
    exclude_keywords: list[str] | None = None
    trigger_mode: TriggerMode | None = None
    risk_threshold: int | None = Field(default=None, ge=0, le=100)
    smart_threshold: dict[str, Any] | None = None
    notify_channels: list[NotifyChannel] | None = None
    notify_config: dict[str, Any] | None = None
    notify_template: str | None = None
    quiet_hours: dict[str, Any] | None = None
    is_active: bool | None = None
    priority: int | None = None


class Subscription(SubscriptionBase):
    id: str
    user_id: str
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class SubscriptionListResponse(BaseModel):
    items: list[Subscription]


class HotItem(BaseModel):
    id: str
    platform: str
    title: str
    url: str
    summary: str | None = None
    cover_image: str | None = None
    hot_value: int = 0
    rank: int = 0
    trend: TrendDirection = TrendDirection.NEW
    risk_score: int | None = None
    risk_level: str | None = None
    risk_assessed_at: datetime | None = None
    first_seen_at: datetime = Field(default_factory=_utc_now)
    last_seen_at: datetime = Field(default_factory=_utc_now)
    last_hot_value: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)
    raw_data: dict[str, Any] = Field(default_factory=dict)


class HotItemListResponse(BaseModel):
    items: list[HotItem]


class MonitorScanRequest(BaseModel):
    platforms: list[str] = Field(default_factory=list)


class MonitorScanResponse(BaseModel):
    scanned_platforms: list[str]
    saved_count: int
    total_fetched: int


class Alert(BaseModel):
    id: str
    hot_item_id: str
    trigger_reason: str
    trigger_mode: TriggerMode
    matched_subscriptions: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    risk_score: int
    risk_level: str
    risk_summary: str | None = None
    hot_item_title: str
    hot_item_url: str
    hot_item_platform: str
    hot_item_hot_value: int
    hot_item_rank: int
    status: AlertStatus = AlertStatus.PENDING
    priority: int = 0
    notify_channels: list[NotifyChannel] = Field(default_factory=list)
    notify_results: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now)
    sent_at: datetime | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    cooldown_until: datetime | None = None


class AlertListResponse(BaseModel):
    items: list[Alert]
