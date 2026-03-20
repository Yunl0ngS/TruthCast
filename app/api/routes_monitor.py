from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Query

from app.schemas.monitor import (
    Alert,
    AlertListResponse,
    HotItemListResponse,
    MonitorScanRequest,
    MonitorScanResponse,
    Subscription,
    SubscriptionCreate,
    SubscriptionListResponse,
    SubscriptionUpdate,
)
from app.services.monitor.alert_engine import AlertEngine
from app.services.monitor.hot_items import HotItemsService
from app.services.monitor.notifier import NotifierService
from app.services.monitor.subscription import SubscriptionService
from app.services.risk_snapshot import detect_risk_snapshot


router = APIRouter(prefix="/monitor", tags=["monitor"])
subscription_service = SubscriptionService()
hot_items_service = HotItemsService()
alert_engine = AlertEngine(
    subscription_service=subscription_service,
    hot_items_service=hot_items_service,
    notifier=NotifierService(),
)


def _default_user_id() -> str:
    return os.getenv("TRUTHCAST_MONITOR_DEFAULT_USER_ID", "demo-user")


@router.get("/subscriptions", response_model=SubscriptionListResponse)
async def list_subscriptions(
    is_active: bool | None = Query(default=None),
) -> SubscriptionListResponse:
    items = await subscription_service.list(_default_user_id(), is_active=is_active)
    return SubscriptionListResponse(items=items)


@router.post("/subscriptions", response_model=Subscription)
async def create_subscription(payload: SubscriptionCreate) -> Subscription:
    return await subscription_service.create(payload, user_id=_default_user_id())


@router.get("/subscriptions/{sub_id}", response_model=Subscription)
async def get_subscription(sub_id: str) -> Subscription:
    subscription = await subscription_service.get(sub_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    return subscription


@router.patch("/subscriptions/{sub_id}", response_model=Subscription)
async def update_subscription(sub_id: str, payload: SubscriptionUpdate) -> Subscription:
    subscription = await subscription_service.update(
        sub_id, payload.model_dump(exclude_none=True)
    )
    if subscription is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    return subscription


@router.delete("/subscriptions/{sub_id}")
async def delete_subscription(sub_id: str) -> dict[str, str]:
    ok = await subscription_service.delete(sub_id)
    if not ok:
        raise HTTPException(status_code=404, detail="subscription not found")
    return {"status": "ok"}


@router.get("/hot-items", response_model=HotItemListResponse)
async def list_hot_items(
    platform: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> HotItemListResponse:
    items = await hot_items_service.list(platform=platform, limit=limit, offset=offset)
    return HotItemListResponse(items=items)


@router.post("/scan", response_model=MonitorScanResponse)
async def trigger_scan(payload: MonitorScanRequest) -> MonitorScanResponse:
    if payload.platforms:
        grouped = {
            platform: await hot_items_service.fetch_platform(platform)
            for platform in payload.platforms
        }
    else:
        grouped = await hot_items_service.fetch_all()

    saved_count = 0
    total_fetched = 0
    for platform, items in grouped.items():
        delta = await hot_items_service.detect_incremental(items, platform)
        total_fetched += len(items)
        saved_count += await hot_items_service.save(items)
        candidates = delta.get("new", []) + delta.get("updated", [])
        if candidates:
            await alert_engine.check_and_alert(candidates, platform)

    return MonitorScanResponse(
        scanned_platforms=list(grouped.keys()),
        saved_count=saved_count,
        total_fetched=total_fetched,
    )


@router.get("/alerts", response_model=AlertListResponse)
async def list_alerts(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AlertListResponse:
    items = await alert_engine.list_alerts(limit=limit, offset=offset)
    return AlertListResponse(items=items)


@router.get("/alerts/{alert_id}", response_model=Alert)
async def get_alert(alert_id: str) -> Alert:
    alert = await alert_engine.get_alert(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    return alert


@router.post("/alerts/{alert_id}/ack")
async def acknowledge_alert(alert_id: str) -> dict[str, str]:
    ok = await alert_engine.acknowledge(alert_id, acknowledged_by=_default_user_id())
    if not ok:
        raise HTTPException(status_code=404, detail="alert not found")
    return {"status": "ok"}


@router.post("/hot-items/{item_id}/assess")
async def assess_hot_item(item_id: str) -> dict[str, object]:
    item = await hot_items_service.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="hot item not found")

    result = (
        await alert_engine.risk_evaluator(item.title)
        if getattr(alert_engine, "risk_evaluator", None)
        else detect_risk_snapshot(item.title)
    )
    await hot_items_service.update_risk(item.id, result.score, result.label)
    updated = await hot_items_service.get(item.id)
    return {
        "item_id": item.id,
        "risk_score": result.score,
        "risk_level": result.label,
        "risk_reasons": result.reasons,
        "updated_at": updated.risk_assessed_at.isoformat() if updated and updated.risk_assessed_at else None,
    }


@router.get("/status")
async def monitor_status() -> dict[str, object]:
    import app.main as main_module

    scheduler = getattr(main_module, "monitor_scheduler", None)
    if scheduler is None:
        return {
            "running": False,
            "adaptive_mode": False,
            "default_interval_minutes": None,
            "effective_interval_minutes": None,
            "platform_intervals": {},
            "last_scan_at": None,
            "last_scan_summary": {},
        }
    return scheduler.get_runtime_status()
