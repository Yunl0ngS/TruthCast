from __future__ import annotations

from uuid import uuid4

from app.schemas.detect import ReportResponse
from app.schemas.monitor import AnalysisStage, HotItem, MonitorAnalysisResult
from app.services.history_store import save_report, update_simulation
from app.services.monitor.platform_config import MonitorPlatformConfig
from app.services.monitor.store import save_monitor_analysis_result
from app.services.news_crawler import crawl_news_url
from app.services.pipeline import (
    align_evidences,
    build_report,
    extract_claims,
    retrieve_evidence,
    simulate_opinion,
)
from app.services.risk_snapshot import detect_risk_snapshot


class MonitorPipelineRunner:
    def __init__(
        self,
        crawl_fn=crawl_news_url,
        risk_fn=detect_risk_snapshot,
        extract_claims_fn=extract_claims,
        retrieve_evidence_fn=retrieve_evidence,
        build_report_fn=build_report,
        simulate_fn=simulate_opinion,
        align_evidences_fn=align_evidences,
    ):
        self.crawl_fn = crawl_fn
        self.risk_fn = risk_fn
        self.extract_claims_fn = extract_claims_fn
        self.retrieve_evidence_fn = retrieve_evidence_fn
        self.build_report_fn = build_report_fn
        self.simulate_fn = simulate_fn
        self.align_evidences_fn = align_evidences_fn

    def process_hot_item(
        self, hot_item: HotItem, config: MonitorPlatformConfig, dedupe_key: str | None = None
    ) -> MonitorAnalysisResult:
        result = MonitorAnalysisResult(
            id=f"analysis_{uuid4().hex[:12]}",
            hot_item_id=hot_item.id,
            platform=hot_item.platform,
            source_url=hot_item.url,
            dedupe_key=dedupe_key,
            current_stage=AnalysisStage.CRAWL,
            simulation_status="pending",
            content_generation_status="idle",
        )

        crawled = self.crawl_fn(hot_item.url)
        if not crawled.success:
            result = result.model_copy(
                update={
                    "crawl_status": "failed",
                    "last_error": crawled.error_msg,
                    "current_stage": AnalysisStage.CRAWL,
                    "simulation_status": "skipped",
                }
            )
            return save_monitor_analysis_result(result)

        result = result.model_copy(
            update={
                "crawl_status": "done",
                "crawl_title": crawled.title,
                "crawl_content": crawled.content,
                "crawl_publish_date": crawled.publish_date,
                "current_stage": AnalysisStage.RISK_SNAPSHOT,
            }
        )

        risk = self.risk_fn(crawled.content)
        result = result.model_copy(
            update={
                "risk_snapshot_score": risk.score,
                "risk_snapshot_label": risk.label,
                "risk_snapshot_reasons": list(risk.reasons or []),
            }
        )
        if risk.score < config.risk_snapshot_threshold:
            result = result.model_copy(
                update={
                    "current_stage": AnalysisStage.RISK_SNAPSHOT,
                    "simulation_status": "skipped",
                }
            )
            return save_monitor_analysis_result(result)

        claims = self.extract_claims_fn(crawled.content)
        raw_evidences = self.retrieve_evidence_fn(claims, strategy=risk.strategy)
        evidences = self.align_evidences_fn(claims, raw_evidences, strategy=risk.strategy)
        report_payload = self.build_report_fn(
            claims,
            evidences,
            original_text=crawled.content,
            strategy=risk.strategy,
            source_url=hot_item.url,
            source_title=crawled.title,
            source_publish_date=crawled.publish_date,
        )
        report = (
            report_payload
            if isinstance(report_payload, ReportResponse)
            else ReportResponse.model_validate(report_payload)
        )
        result = result.model_copy(
            update={
                "current_stage": AnalysisStage.REPORT,
                "raw_evidences": [item.model_dump() for item in raw_evidences],
                "evidences": [item.model_dump() for item in evidences],
                "report_score": report.risk_score,
                "report_level": report.risk_level,
                "report_data": report.model_dump(),
            }
        )
        history_record_id = save_report(
            input_text=crawled.content or "[无原文]",
            report=report.model_dump(),
            detect_data={
                "label": risk.label,
                "confidence": risk.confidence,
                "score": risk.score,
                "reasons": list(risk.reasons or []),
            },
        )
        result = result.model_copy(update={"history_record_id": history_record_id})
        if report.risk_score < config.report_threshold_for_simulation:
            result = result.model_copy(update={"simulation_status": "skipped"})
            return save_monitor_analysis_result(result)

        simulation = self.simulate_fn(
            crawled.content,
            platform=hot_item.platform,
            claims=claims,
            evidences=evidences,
            report=report,
        )
        result = result.model_copy(
            update={
                "current_stage": AnalysisStage.SIMULATION,
                "simulation_status": "done",
                "simulation_data": simulation.model_dump(),
            }
        )
        if result.history_record_id:
            update_simulation(result.history_record_id, simulation.model_dump())
        return save_monitor_analysis_result(result)
