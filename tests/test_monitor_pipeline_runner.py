from __future__ import annotations

from datetime import datetime, timezone
import sqlite3


def test_monitor_analysis_result_store_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))

    from app.schemas.monitor import AnalysisStage, MonitorAnalysisResult
    from app.services.monitor.store import (
        get_monitor_analysis_result,
        init_monitor_db,
        list_monitor_analysis_results,
        save_monitor_analysis_result,
    )

    init_monitor_db()

    saved = save_monitor_analysis_result(
        MonitorAnalysisResult(
            id="analysis_1",
            hot_item_id="hot_1",
            platform="thepaper",
            source_url="https://example.com/news/1",
            dedupe_key="thepaper::示例新闻::https://example.com/news/1",
            crawl_status="done",
            crawl_title="示例新闻",
            crawl_content="这是一段已抓取的新闻正文",
            crawl_publish_date="2026-03-20",
            risk_snapshot_score=48,
            risk_snapshot_label="suspicious",
            risk_snapshot_reasons=["存在来源不明表述", "缺少权威证据支撑"],
            current_stage=AnalysisStage.REPORT,
            report_score=56,
            report_level="high",
            simulation_status="pending",
            content_generation_status="idle",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )

    loaded = get_monitor_analysis_result(saved.id)
    assert loaded is not None
    assert loaded.hot_item_id == "hot_1"
    assert loaded.report_score == 56
    assert loaded.current_stage == AnalysisStage.REPORT
    assert loaded.dedupe_key == "thepaper::示例新闻::https://example.com/news/1"
    assert loaded.risk_snapshot_reasons == ["存在来源不明表述", "缺少权威证据支撑"]

    items = list_monitor_analysis_results(limit=10)
    assert [item.id for item in items] == ["analysis_1"]


def test_init_monitor_db_migrates_existing_analysis_table(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "monitor.db"
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(db_path))

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE monitor_analysis_results (
                id TEXT PRIMARY KEY,
                hot_item_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                source_url TEXT NOT NULL,
                crawl_status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()

    from app.services.monitor.store import init_monitor_db, monitor_connection

    init_monitor_db()

    with monitor_connection() as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(monitor_analysis_results)").fetchall()
        }

    assert "report_data_json" in columns
    assert "simulation_data_json" in columns
    assert "content_data_json" in columns
    assert "risk_snapshot_reasons_json" in columns
    assert "dedupe_key" in columns


def test_monitor_scan_window_store_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))

    from app.schemas.monitor import (
        AnalysisStage,
        MonitorAnalysisResult,
        MonitorScanTriggerType,
        MonitorScanWindow,
        MonitorScanWindowStatus,
        MonitorWindowItem,
    )
    from app.services.monitor.store import (
        create_monitor_scan_window,
        list_monitor_scan_window_details,
        save_monitor_analysis_result,
        save_monitor_window_item,
    )

    window = create_monitor_scan_window(
        MonitorScanWindow(
            id="window_1",
            window_start=datetime(2026, 3, 21, 15, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 3, 21, 16, 0, tzinfo=timezone.utc),
            trigger_type=MonitorScanTriggerType.SCHEDULED,
            status=MonitorScanWindowStatus.COMPLETED,
            platforms=["thepaper", "zaobao"],
            fetched_count=12,
            deduplicated_count=10,
            analyzed_count=7,
            duplicate_count=3,
        )
    )

    analysis = save_monitor_analysis_result(
        MonitorAnalysisResult(
            id="analysis_window_1",
            hot_item_id="hot_window_1",
            platform="thepaper",
            source_url="https://example.com/news/window",
            dedupe_key="thepaper::窗口新闻::https://example.com/news/window",
            crawl_status="done",
            current_stage=AnalysisStage.RISK_SNAPSHOT,
            risk_snapshot_score=52,
            risk_snapshot_label="suspicious",
            risk_snapshot_reasons=["窗口新闻存在争议"],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )

    save_monitor_window_item(
        MonitorWindowItem(
            id="window_item_1",
            window_id=window.id,
            platform="thepaper",
            hot_item_id="hot_window_1",
            analysis_result_id=analysis.id,
            dedupe_key="thepaper::窗口新闻::https://example.com/news/window",
            title="窗口新闻",
            url="https://example.com/news/window",
            hot_value=88,
            rank=1,
            trend="new",
        )
    )

    details = list_monitor_scan_window_details(limit=10)

    assert len(details) == 1
    assert details[0].window.id == "window_1"
    assert details[0].window.fetched_count == 12
    assert len(details[0].items) == 1
    assert details[0].items[0].analysis_result is not None
    assert details[0].items[0].analysis_result.id == "analysis_window_1"


def test_monitor_window_item_store_deduplicates_by_window_and_dedupe_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))

    from app.schemas.monitor import (
        MonitorScanTriggerType,
        MonitorScanWindow,
        MonitorScanWindowStatus,
        MonitorWindowItem,
    )
    from app.services.monitor.store import (
        create_monitor_scan_window,
        list_monitor_window_items,
        save_monitor_window_item,
    )

    window = create_monitor_scan_window(
        MonitorScanWindow(
            id="window_dedupe",
            window_start=datetime(2026, 3, 21, 16, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 3, 21, 17, 0, tzinfo=timezone.utc),
            trigger_type=MonitorScanTriggerType.MANUAL,
            status=MonitorScanWindowStatus.COMPLETED,
            platforms=["thepaper"],
        )
    )

    save_monitor_window_item(
        MonitorWindowItem(
            id="window_item_first",
            window_id=window.id,
            platform="thepaper",
            hot_item_id="hot_first",
            dedupe_key="thepaper::同一新闻::https://example.com/news/1",
            title="同一新闻",
            url="https://example.com/news/1",
            hot_value=80,
            rank=1,
            trend="new",
        )
    )
    save_monitor_window_item(
        MonitorWindowItem(
            id="window_item_second",
            window_id=window.id,
            platform="thepaper",
            hot_item_id="hot_second",
            dedupe_key="thepaper::同一新闻::https://example.com/news/1",
            title="同一新闻（更新）",
            url="https://example.com/news/1",
            hot_value=95,
            rank=1,
            trend="rising",
        )
    )

    items = list_monitor_window_items(window.id)
    assert len(items) == 1
    assert items[0].hot_item_id == "hot_second"
    assert items[0].title == "同一新闻（更新）"
    assert items[0].hot_value == 95


def test_pipeline_runner_stops_after_low_risk_snapshot(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))

    from app.schemas.monitor import HotItem
    from app.services.monitor.platform_config import MonitorPlatformConfig
    from app.services.monitor.pipeline_runner import MonitorPipelineRunner

    hot_item = HotItem(
        id="hot_low",
        platform="thepaper",
        title="低风险新闻",
        url="https://example.com/news/low",
        hot_value=10,
        rank=1,
    )
    config = MonitorPlatformConfig(
        key="thepaper",
        display_name="澎湃新闻",
        newsnow_id="thepaper",
        enabled=True,
        scan_interval_minutes=60,
        fetch_top_n=10,
        risk_snapshot_threshold=40,
        report_threshold_for_simulation=50,
    )

    class _RiskResult:
        label = "credible"
        confidence = 0.8
        score = 20
        reasons = ["低风险"]
        strategy = None

    runner = MonitorPipelineRunner(
        crawl_fn=lambda url: type(
            "CrawledNews",
            (),
            {
                "title": "低风险新闻",
                "content": "这是一篇低风险新闻正文",
                "publish_date": "2026-03-20",
                "source_url": url,
                "success": True,
                "error_msg": "",
            },
        )(),
        risk_fn=lambda text: _RiskResult(),
    )

    result = runner.process_hot_item(hot_item, config)

    assert result.current_stage.value == "risk_snapshot"
    assert result.risk_snapshot_score == 20
    assert result.risk_snapshot_reasons == ["低风险"]
    assert result.report_score is None
    assert result.simulation_status == "skipped"


def test_pipeline_runner_runs_simulation_when_report_score_ge_threshold(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))

    from app.schemas.detect import ClaimItem, EvidenceItem, ReportResponse, SimulateResponse, SuggestionData
    from app.schemas.monitor import HotItem
    from app.services.monitor.platform_config import MonitorPlatformConfig
    from app.services.monitor.pipeline_runner import MonitorPipelineRunner

    hot_item = HotItem(
        id="hot_high",
        platform="zaobao",
        title="高风险新闻",
        url="https://example.com/news/high",
        hot_value=20,
        rank=1,
    )
    config = MonitorPlatformConfig(
        key="zaobao",
        display_name="联合早报",
        newsnow_id="zaobao",
        enabled=True,
        scan_interval_minutes=60,
        fetch_top_n=10,
        risk_snapshot_threshold=40,
        report_threshold_for_simulation=50,
    )

    class _RiskResult:
        label = "suspicious"
        confidence = 0.9
        score = 58
        reasons = ["存在风险"]
        strategy = None

    claim = ClaimItem(
        claim_id="c1",
        claim_text="某事件发生",
        source_sentence="某事件发生",
    )
    evidence = EvidenceItem(
        evidence_id="e1",
        claim_id="c1",
        title="证据",
        source="source",
        url="https://example.com/e1",
        published_at="2026-03-20",
        summary="证据摘要",
        stance="refute",
        source_weight=0.8,
    )
    report = ReportResponse(
        risk_score=66,
        risk_level="critical",
        risk_label="likely_misinformation",
        detected_scenario="general",
        evidence_domains=["general"],
        source_url=hot_item.url,
        source_title="高风险新闻",
        source_publish_date="2026-03-20",
        summary="高风险摘要",
        suspicious_points=["存在疑点"],
        claim_reports=[],
    )
    simulation = SimulateResponse(
        emotion_distribution={"anger": 0.5, "neutral": 0.5},
        stance_distribution={"questioning": 0.6, "neutral": 0.4},
        narratives=[],
        flashpoints=["传播加速"],
        suggestion=SuggestionData(summary="需要尽快回应", actions=[]),
    )

    runner = MonitorPipelineRunner(
        crawl_fn=lambda url: type(
            "CrawledNews",
            (),
            {
                "title": "高风险新闻",
                "content": "这是一篇高风险新闻正文",
                "publish_date": "2026-03-20",
                "source_url": url,
                "success": True,
                "error_msg": "",
            },
        )(),
        risk_fn=lambda text: _RiskResult(),
        extract_claims_fn=lambda text, strategy=None: [claim],
        retrieve_evidence_fn=lambda claims, strategy=None: [evidence],
        build_report_fn=lambda claims, evidences, **kwargs: report.model_dump(),
        simulate_fn=lambda text, **kwargs: simulation,
    )

    result = runner.process_hot_item(hot_item, config)

    assert result.current_stage.value == "simulation"
    assert result.report_score == 66
    assert result.risk_snapshot_reasons == ["存在风险"]
    assert result.simulation_status == "done"


def test_pipeline_runner_persists_raw_and_aligned_evidences(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))

    from app.schemas.detect import ClaimItem, EvidenceItem, ReportResponse, SimulateResponse, SuggestionData
    from app.schemas.monitor import HotItem
    from app.services.monitor.platform_config import MonitorPlatformConfig
    from app.services.monitor.pipeline_runner import MonitorPipelineRunner

    hot_item = HotItem(
        id="hot_evidence",
        platform="thepaper",
        title="需要完整证据链的新闻",
        url="https://example.com/news/evidence",
        hot_value=30,
        rank=1,
    )
    config = MonitorPlatformConfig(
        key="thepaper",
        display_name="澎湃新闻",
        newsnow_id="thepaper",
        enabled=True,
        scan_interval_minutes=60,
        fetch_top_n=10,
        risk_snapshot_threshold=40,
        report_threshold_for_simulation=50,
    )

    class _RiskResult:
        label = "suspicious"
        confidence = 0.9
        score = 66
        reasons = ["存在风险"]
        strategy = None

    claim = ClaimItem(
        claim_id="c1",
        claim_text="示例主张",
        source_sentence="原始句子",
    )
    raw_evidence = EvidenceItem(
        evidence_id="e1",
        claim_id="c1",
        title="原始检索证据",
        source="web",
        url="https://example.com/raw",
        published_at="2026-03-21",
        summary="原始摘要",
        stance="insufficient",
        source_weight=0.6,
        source_type="web_live",
    )
    aligned_evidence = EvidenceItem(
        evidence_id="e2",
        claim_id="c1",
        title="聚合对齐证据",
        source="web_summary",
        url="https://example.com/aligned",
        published_at="2026-03-21",
        summary="聚合摘要",
        stance="refute",
        source_weight=0.8,
        source_type="web_summary",
        alignment_rationale="与主张矛盾",
        alignment_confidence=0.88,
    )
    report = ReportResponse(
        risk_score=62,
        risk_level="high",
        risk_label="suspicious",
        detected_scenario="general",
        evidence_domains=["general"],
        source_url=hot_item.url,
        source_title="需要完整证据链的新闻",
        source_publish_date="2026-03-21",
        summary="报告摘要",
        suspicious_points=["疑点"],
        claim_reports=[],
    )
    simulation = SimulateResponse(
        emotion_distribution={"anger": 0.4, "neutral": 0.6},
        stance_distribution={"questioning": 0.7, "neutral": 0.3},
        narratives=[],
        flashpoints=["扩散"],
        suggestion=SuggestionData(summary="建议", actions=[]),
    )

    runner = MonitorPipelineRunner(
        crawl_fn=lambda url: type(
            "CrawledNews",
            (),
            {
                "title": "需要完整证据链的新闻",
                "content": "新闻正文内容",
                "publish_date": "2026-03-21",
                "source_url": url,
                "success": True,
                "error_msg": "",
            },
        )(),
        risk_fn=lambda text: _RiskResult(),
        extract_claims_fn=lambda text, strategy=None: [claim],
        retrieve_evidence_fn=lambda claims, strategy=None: [raw_evidence],
        align_evidences_fn=lambda claims, evidences, strategy=None: [aligned_evidence],
        build_report_fn=lambda claims, evidences, **kwargs: report.model_dump(),
        simulate_fn=lambda text, **kwargs: simulation,
    )

    result = runner.process_hot_item(hot_item, config)

    assert len(result.raw_evidences) == 1
    assert result.raw_evidences[0]["title"] == "原始检索证据"
    assert len(result.evidences) == 1
    assert result.evidences[0]["title"] == "聚合对齐证据"
    assert result.evidences[0]["source_type"] == "web_summary"


def test_pipeline_runner_persists_history_record_for_monitor_analysis(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))
    monkeypatch.setenv("TRUTHCAST_HISTORY_DB_PATH", str(tmp_path / "history.db"))

    from app.schemas.detect import ClaimItem, EvidenceItem, ReportResponse, SimulateResponse, SuggestionData
    from app.schemas.monitor import HotItem
    from app.services.history_store import get_history
    from app.services.monitor.platform_config import MonitorPlatformConfig
    from app.services.monitor.pipeline_runner import MonitorPipelineRunner

    hot_item = HotItem(
        id="hot_history",
        platform="thepaper",
        title="会写入历史记录的新闻",
        url="https://example.com/news/history",
        hot_value=30,
        rank=1,
    )
    config = MonitorPlatformConfig(
        key="thepaper",
        display_name="澎湃新闻",
        newsnow_id="thepaper",
        enabled=True,
        scan_interval_minutes=60,
        fetch_top_n=10,
        risk_snapshot_threshold=40,
        report_threshold_for_simulation=50,
    )

    class _RiskResult:
        label = "suspicious"
        confidence = 0.9
        score = 66
        reasons = ["存在风险"]
        strategy = None

    claim = ClaimItem(
        claim_id="c1",
        claim_text="示例主张",
        source_sentence="原始句子",
    )
    evidence = EvidenceItem(
        evidence_id="e1",
        claim_id="c1",
        title="对齐证据",
        source="web_summary",
        url="https://example.com/e1",
        published_at="2026-03-21",
        summary="聚合摘要",
        stance="refute",
        source_weight=0.8,
        source_type="web_summary",
    )
    report = ReportResponse(
        risk_score=62,
        risk_level="high",
        risk_label="suspicious",
        detected_scenario="general",
        evidence_domains=["general"],
        source_url=hot_item.url,
        source_title="会写入历史记录的新闻",
        source_publish_date="2026-03-21",
        summary="报告摘要",
        suspicious_points=["疑点"],
        claim_reports=[],
    )
    simulation = SimulateResponse(
        emotion_distribution={"anger": 0.4, "neutral": 0.6},
        stance_distribution={"questioning": 0.7, "neutral": 0.3},
        narratives=[],
        flashpoints=["扩散"],
        suggestion=SuggestionData(summary="建议", actions=[]),
    )

    runner = MonitorPipelineRunner(
        crawl_fn=lambda url: type(
            "CrawledNews",
            (),
            {
                "title": "会写入历史记录的新闻",
                "content": "新闻正文内容",
                "publish_date": "2026-03-21",
                "source_url": url,
                "success": True,
                "error_msg": "",
            },
        )(),
        risk_fn=lambda text: _RiskResult(),
        extract_claims_fn=lambda text, strategy=None: [claim],
        retrieve_evidence_fn=lambda claims, strategy=None: [evidence],
        align_evidences_fn=lambda claims, evidences, strategy=None: [evidence],
        build_report_fn=lambda claims, evidences, **kwargs: report.model_dump(),
        simulate_fn=lambda text, **kwargs: simulation,
    )

    result = runner.process_hot_item(hot_item, config)

    assert result.history_record_id
    history = get_history(result.history_record_id)
    assert history is not None
    assert history["input_text"] == "新闻正文内容"
    assert history["report"]["summary"] == "报告摘要"
    assert history["detect_data"]["score"] == 66
    assert history["simulation"]["flashpoints"] == ["扩散"]
