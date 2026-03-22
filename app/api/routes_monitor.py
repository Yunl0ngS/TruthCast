from __future__ import annotations

import os
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query

from app.schemas.detect import ContentDraftData, ContentGenerateRequest, ReportResponse, SimulateResponse
from app.schemas.monitor import (
    Alert,
    AlertListResponse,
    HotItemListResponse,
    HotItem,
    MonitorAnalysisResult,
    MonitorAnalysisResultListResponse,
    MonitorScanWindowDetail,
    MonitorScanWindowHistoryResponse,
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
from app.services.monitor.pipeline_runner import MonitorPipelineRunner
from app.services.monitor.store import (
    get_monitor_analysis_result,
    get_monitor_window_item,
    get_latest_monitor_scan_window_detail,
    list_monitor_analysis_results,
    list_monitor_scan_window_details,
    save_monitor_analysis_result,
    update_monitor_window_item_analysis_result,
)
from app.services.monitor.subscription import SubscriptionService
from app.services.content_generation import generate_full_content
from app.services.history_store import update_content
from app.services.risk_snapshot import detect_risk_snapshot


router = APIRouter(prefix="/monitor", tags=["monitor"])
subscription_service = SubscriptionService()
hot_items_service = HotItemsService()
pipeline_runner = MonitorPipelineRunner()


def _default_user_id() -> str:
    return os.getenv("TRUTHCAST_MONITOR_DEFAULT_USER_ID", "demo-user")


def _manual_scan_auto_analyze_default() -> bool:
    return os.getenv("TRUTHCAST_MONITOR_MANUAL_SCAN_AUTO_ANALYZE", "false").strip().lower() == "true"


def _alert_cooldown_minutes() -> int:
    try:
        return max(1, int(os.getenv("TRUTHCAST_MONITOR_ALERT_COOLDOWN_MINUTES", "30")))
    except (TypeError, ValueError):
        return 30


alert_engine = AlertEngine(
    subscription_service=subscription_service,
    hot_items_service=hot_items_service,
    notifier=NotifierService(),
    cooldown_minutes=_alert_cooldown_minutes(),
)


def _enabled_platforms_payload() -> list[dict[str, str]]:
    return [
        {"key": item.key, "display_name": item.display_name}
        for item in getattr(hot_items_service, "platform_configs", [])
    ]


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
    import app.main as main_module

    scheduler = getattr(main_module, "monitor_scheduler", None)
    resolved_auto_analyze = (
        _manual_scan_auto_analyze_default()
        if payload.auto_analyze is None
        else payload.auto_analyze
    )
    if scheduler is not None:
        result = await scheduler.trigger_manual_scan(
            payload.platforms or None,
            auto_analyze=resolved_auto_analyze,
        )
        return MonitorScanResponse(**result)

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
        if resolved_auto_analyze and candidates:
            await alert_engine.check_and_alert(candidates, platform)
            config = next(
                (item for item in hot_items_service.platform_configs if item.key == platform),
                None,
            )
            if config is not None:
                for candidate in candidates:
                    pipeline_runner.process_hot_item(candidate, config)

    return MonitorScanResponse(
        scanned_platforms=list(grouped.keys()),
        saved_count=saved_count,
        total_fetched=total_fetched,
        auto_analyze=resolved_auto_analyze,
        analysis_scheduled=resolved_auto_analyze,
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
            "manual_scan_auto_analyze_default": _manual_scan_auto_analyze_default(),
            "enabled_platforms": _enabled_platforms_payload(),
            "default_interval_minutes": None,
            "effective_interval_minutes": None,
            "platform_intervals": {},
            "last_scan_at": None,
            "last_scan_summary": {},
        }
    return scheduler.get_runtime_status()


@router.get("/analysis-results", response_model=MonitorAnalysisResultListResponse)
async def list_analysis_results(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> MonitorAnalysisResultListResponse:
    return MonitorAnalysisResultListResponse(
        items=list_monitor_analysis_results(limit=limit, offset=offset)
    )


@router.get("/analysis-results/{result_id}", response_model=MonitorAnalysisResult)
async def get_analysis_result(result_id: str) -> MonitorAnalysisResult:
    result = get_monitor_analysis_result(result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="analysis result not found")
    return result


@router.post("/window-items/{item_id}/analyze")
async def analyze_window_item(item_id: str) -> dict[str, MonitorAnalysisResult]:
    item = get_monitor_window_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="window item not found")

    config = next(
        (platform for platform in hot_items_service.platform_configs if platform.key == item.platform),
        None,
    )
    if config is None:
        raise HTTPException(status_code=400, detail="platform is not enabled")

    analysis_result = pipeline_runner.process_hot_item(
        hot_item=HotItem(
            id=item.hot_item_id or item.id,
            platform=item.platform,
            title=item.title,
            url=item.url,
            hot_value=item.hot_value,
            rank=item.rank,
            trend=item.trend,
        ),
        config=config,
        dedupe_key=item.dedupe_key,
    )
    persisted = save_monitor_analysis_result(analysis_result)
    update_monitor_window_item_analysis_result(
        window_id=item.window_id,
        dedupe_key=item.dedupe_key,
        analysis_result_id=persisted.id,
    )
    return {"analysis_result": persisted}


@router.post("/analysis-results/{result_id}/generate-content")
async def generate_analysis_content(result_id: str) -> dict[str, str]:
    result = get_monitor_analysis_result(result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="analysis result not found")
    if result.simulation_status != "done" or not result.simulation_data or not result.report_data:
        raise HTTPException(status_code=400, detail="simulation not completed")

    content_response = await generate_full_content(
        ContentGenerateRequest(
            text=result.crawl_content or "",
            report=ReportResponse.model_validate(result.report_data),
            simulation=SimulateResponse.model_validate(result.simulation_data),
        )
    )
    updated = result.model_copy(
        update={
            "content_generation_status": "done",
            "content_data": ContentDraftData.model_validate(content_response),
        }
    )
    save_monitor_analysis_result(updated)
    if updated.history_record_id:
        update_content(updated.history_record_id, updated.content_data.model_dump())
    return {"status": "ok", "result_id": result_id}


@router.get("/windows/latest", response_model=MonitorScanWindowDetail)
async def get_latest_window() -> MonitorScanWindowDetail:
    detail = get_latest_monitor_scan_window_detail()
    if detail is None:
        raise HTTPException(status_code=404, detail="latest window not found")
    return detail


@router.get("/windows/history", response_model=MonitorScanWindowHistoryResponse)
async def get_window_history(
    hours: int = Query(default=6, ge=1, le=168),
    limit: int = Query(default=24, ge=1, le=168),
) -> MonitorScanWindowHistoryResponse:
    latest = get_latest_monitor_scan_window_detail()
    if latest is None:
        return MonitorScanWindowHistoryResponse(windows=[])

    history_end = latest.window.window_start
    history_start = history_end - timedelta(hours=hours)
    details = list_monitor_scan_window_details(
        start=history_start,
        end=history_end,
        limit=limit,
    )
    details = [detail for detail in details if detail.window.id != latest.window.id]
    return MonitorScanWindowHistoryResponse(windows=details)
