"""Simulate command - Opinion simulation and prediction."""

import json
import sys
from typing import Any

import typer

from app.cli.client import APIClient, APIError
from app.cli.config import get_config
from app.cli.lib.state_manager import load_state

def _format_emotion_stage(data: dict[str, Any]) -> None:
    """Format and display emotion & stance analysis stage."""
    emotion_dist = data.get("emotion_distribution", {})
    stance_dist = data.get("stance_distribution", {})
    
    typer.echo("\n" + "="*60)
    typer.echo("[STAGE 1] 第一阶段：情绪与立场分析 (Emotion & Stance Analysis)")
    typer.echo("="*60)
    
    if emotion_dist:
        typer.echo("\n情绪分布 (Emotion Distribution):")
        for emotion, percentage in emotion_dist.items():
            bar_length = int(percentage / 5)
            bar = "█" * bar_length + "░" * (20 - bar_length)
            typer.echo(f"  {emotion:12s} {bar} {percentage:5.1f}%")
    
    if stance_dist:
        typer.echo("\n立场分布 (Stance Distribution):")
        for stance, count in stance_dist.items():
            typer.echo(f"  {stance}: {count}")
    
    drivers = data.get("emotion_drivers", [])
    if drivers:
        typer.echo("\n情绪驱动因素 (Emotion Drivers):")
        for i, driver in enumerate(drivers, 1):
            typer.echo(f"  {i}. {driver}")


def _format_narratives_stage(data: dict[str, Any]) -> None:
    """Format and display narrative branches stage."""
    narratives = data.get("narratives", [])
    
    typer.echo("\n" + "="*60)
    typer.echo("[STAGE 2] 第二阶段：叙事分支生成 (Narrative Branch Generation)")
    typer.echo("="*60)
    
    if narratives:
        for i, narrative in enumerate(narratives, 1):
            typer.echo(f"\n  分支 {i}: {narrative.get('title', 'N/A')}")
            if narrative.get("description"):
                typer.echo(f"    描述: {narrative['description']}")
            if narrative.get("spread_potential"):
                typer.echo(f"    传播潜力: {narrative['spread_potential']}")
            if narrative.get("trigger_keywords"):
                keywords = narrative["trigger_keywords"]
                if isinstance(keywords, str):
                    keywords = [keywords]
                typer.echo(f"    触发词: {', '.join(keywords)}")
    else:
        typer.echo("  (无叙事分支)")


def _format_flashpoints_stage(data: dict[str, Any]) -> None:
    """Format and display flashpoint identification stage."""
    flashpoints = data.get("flashpoints", [])
    
    typer.echo("\n" + "="*60)
    typer.echo("[STAGE 3] 第三阶段：引爆点识别 (Flashpoint Identification)")
    typer.echo("="*60)
    
    if flashpoints:
        for i, flashpoint in enumerate(flashpoints, 1):
            typer.echo(f"\n  引爆点 {i}: {flashpoint.get('trigger', 'N/A')}")
            if flashpoint.get("risk_level"):
                typer.echo(f"    风险等级: {flashpoint['risk_level']}")
            if flashpoint.get("estimated_reach"):
                typer.echo(f"    预估传播范围: {flashpoint['estimated_reach']}")
            if flashpoint.get("impact"):
                typer.echo(f"    影响: {flashpoint['impact']}")
    else:
        typer.echo("  (无明显引爆点)")


def _format_suggestion_stage(data: dict[str, Any]) -> None:
    """Format and display mitigation suggestions stage."""
    suggestion = data.get("suggestion", {})
    
    typer.echo("\n" + "="*60)
    typer.echo("[STAGE 4] 第四阶段：应对建议 (Mitigation Suggestions)")
    typer.echo("="*60)
    
    if suggestion.get("summary"):
        typer.echo(f"\n摘要: {suggestion['summary']}")
    
    actions = suggestion.get("actions", [])
    if actions:
        typer.echo("\n建议行动:")
        for i, action in enumerate(actions, 1):
            typer.echo(f"\n  {i}. {action.get('action', 'N/A')}")
            if action.get("priority"):
                typer.echo(f"     优先级: {action['priority']}")
            if action.get("timeline"):
                typer.echo(f"     时间线: {action['timeline']}")
            if action.get("category"):
                typer.echo(f"     类别: {action['category']}")
    else:
        typer.echo("\n  (无具体建议)")


def _parse_sse_event(line: str) -> dict[str, Any] | None:
    """Parse SSE event line format: data: {json}."""
    if not line.startswith("data: "):
        return None
    try:
        json_str = line[6:]  # Remove "data: " prefix
        return json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return None


def simulate(
    stream: bool = typer.Option(
        True,
        "--stream/--no-stream",
        help="Use SSE streaming for real-time output"
    ),
    record: str = typer.Option(
        None,
        "--record",
        "-r",
        help="Record ID from history (uses bound record_id if not specified)"
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output raw JSON instead of formatted text"
    )
) -> None:
    """
    Simulate opinion evolution and public response.
    
    Generates:
    - Emotion and stance analysis
    - Narrative branch predictions
    - Flashpoint identification
    - Mitigation suggestions
    
    Supports SSE streaming for incremental output.
    """
    config = get_config()
    
    # Resolve record_id: explicit > bound > error
    if not record:
        state = load_state()
        record = state.get("bound_record_id")
        if not record:
            typer.echo("[ERROR] 缺少 record_id. 用法: truthcast simulate --record <record_id>", err=True)
            typer.echo("   或先用 'truthcast bind <record_id>' 绑定默认记录", err=True)
            raise typer.Exit(code=1)
    
    client = APIClient(
        base_url=config.api_base,
        timeout=config.timeout,
        retry_times=config.retry_times
    )
    
    # Fetch history detail to get claims/evidences/report
    try:
        history_detail = client.get(f"/history/{record}")
    except APIError as e:
        if e.status_code == 404:
            typer.echo(f"[ERROR] 记录不存在: {record}", err=True)
        else:
            typer.echo(e.user_friendly_message(), err=True)
        raise typer.Exit(code=1)
    
    # Prepare simulate request payload
    payload = {
        "text": history_detail.get("input_preview", ""),
        "claims": history_detail.get("report", {}).get("claims", []) if history_detail.get("report") else [],
        "evidences": history_detail.get("evidences", []),
        "report": history_detail.get("report"),
        "time_window_hours": 24,
        "platform": "general",
        "comments": [],
    }
    
    if stream:
        # SSE streaming mode
        if not json_output:
            typer.echo(f"[STREAM] 正在流式输出舆情预演结果... (record_id: {record})")
            typer.echo("Press Ctrl+C to cancel\n")
        
        try:
            # Call /simulate/stream with raw response using stream method
            with client.stream(
                "POST",
                "/simulate/stream",
                json=payload,
            ) as response:
                
                if response.status_code != 200:
                    typer.echo(f"[ERROR] 舆情预演失败: HTTP {response.status_code}", err=True)
                    raise typer.Exit(code=1)
                
                # Parse SSE stream
                buffer = ""
                accumulated_data = {}
                
                for chunk in response.iter_lines(decode_unicode=True):
                    if not chunk:
                        continue
                    
                    # Handle potential chunk buffering
                    buffer += chunk
                    
                    # Try to parse complete SSE events
                    while "\n" in buffer or buffer.startswith("data: "):
                        if "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                        else:
                            line = buffer
                            buffer = ""
                        
                        event = _parse_sse_event(line)
                        if event:
                            stage = event.get("stage")
                            if json_output:
                                typer.echo(json.dumps(event, ensure_ascii=False))
                            else:
                                # Accumulate data and format by stage
                                if stage == "emotion":
                                    accumulated_data.update(event)
                                    _format_emotion_stage(event)
                                elif stage == "narratives":
                                    accumulated_data.update(event)
                                    _format_narratives_stage(event)
                                elif stage == "flashpoints":
                                    accumulated_data.update(event)
                                    _format_flashpoints_stage(event)
                                elif stage == "suggestion":
                                    accumulated_data.update(event)
                                    _format_suggestion_stage(event)
                                    # Final stage: add separator
                                    if not json_output:
                                        typer.echo("\n" + "="*60)
                                        typer.echo("[SUCCESS] 舆情预演完成 (Complete)")
                                        typer.echo("="*60 + "\n")
        
        except KeyboardInterrupt:
            if not json_output:
                typer.echo("\n\n[CANCELLED] 预演已取消 (Cancelled by user)", err=True)
            raise typer.Exit(code=130)
        except Exception as e:
            if not json_output:
                typer.echo(f"[ERROR] 流式传输错误: {str(e)}", err=True)
            raise typer.Exit(code=1)
    
    else:
        # Non-streaming mode (fetch complete result)
        if not json_output:
            typer.echo(f"[LOADING] 正在生成舆情预演结果... (record_id: {record})")
        try:
            result = client.post("/simulate", json=payload)
            
            if json_output:
                typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                typer.echo("\n[SUCCESS] 舆情预演完成")
                typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        
        except APIError as e:
            typer.echo(e.user_friendly_message(), err=True)
            raise typer.Exit(code=1)
        except Exception as e:
            typer.echo(f"[ERROR] 舆情预演失败: {str(e)}", err=True)
            raise typer.Exit(code=1)
