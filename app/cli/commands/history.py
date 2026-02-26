"""History command - List and display analysis records."""

import json
import sys
from datetime import datetime
from typing import Optional

import typer

from app.cli.client import APIClient, APIError
from app.cli._globals import get_global_config
from app.cli.lib.safe_output import emoji, safe_print, safe_print_err


def _format_timestamp(ts: str) -> str:
    """Format ISO timestamp to readable format."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts


def _format_score(label: str, score: int) -> str:
    """Format risk score with label and colored indicator."""
    colors = {
        "高风险": emoji("🔴", "[HIGH]"),
        "中风险": emoji("🟠", "[MED]"),
        "低风险": emoji("🟢", "[LOW]"),
        "可信": emoji("✅", "[OK]"),
    }
    color = colors.get(label, "")
    return f"{color} {label} ({score})"


def _truncate_text(text: str, max_len: int = 60) -> str:
    """Truncate text to max length."""
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


history_app = typer.Typer(help="Manage analysis history records")


@history_app.command("list")
def list_history(
    limit: int = typer.Option(10, "--limit", "-l", help="Number of records to show"),
    format_type: str = typer.Option("text", "--format", help="Output format: text (default) or json"),
) -> None:
    """List recent analysis records."""
    try:
        config = get_global_config()
        client = APIClient(config.api_base_url, timeout_sec=config.timeout_sec)
        
        response = client.get("/history", params={"limit": limit})
        
        if isinstance(response, dict) and "items" in response:
            items = response["items"]
        else:
            items = response if isinstance(response, list) else []
        
        if not items:
            safe_print(emoji("📭", "[EMPTY]") + " 暂无历史分析记录")
            return
        
        if format_type == "json":
            safe_print(json.dumps(items, indent=2, ensure_ascii=False))
        else:
            safe_print(f"\n{emoji('📋', '[LIST]')} 历史分析记录 (最近{len(items)}条)\n")
            safe_print(f"{'序号':<4} {'Record ID':<15} {'时间':<16} {'风险评估':<15} {'摘要'}")
            safe_print("-" * 100)
            
            for idx, item in enumerate(items, 1):
                record_id = item.get("record_id", "N/A")[:14]
                created_at = _format_timestamp(item.get("created_at", ""))
                risk_label = item.get("risk_label", "未知")
                risk_score = item.get("risk_score", 0)
                summary = _truncate_text(item.get("summary", ""))
                
                score_str = _format_score(risk_label, risk_score)
                safe_print(f"{idx:<4} {record_id:<15} {created_at:<16} {score_str:<30} {summary}")
            
            safe_print("")
            safe_print(emoji("💡", "[TIP]") + " 提示: 使用 'truthcast history show <record_id>' 查看详情")
            safe_print(emoji("💡", "[TIP]") + " 提示: 使用 'truthcast state bind <record_id>' 绑定记录 ID\n")
    
    except APIError as e:
        safe_print_err(f"\n{e.user_friendly_message()}")
        sys.exit(1)
    except Exception as e:
        safe_print_err(f"\n{emoji('❌', '[ERROR]')} 未知错误: {e}")
        sys.exit(1)


@history_app.command("show")
def show_history(
    record_id: Optional[str] = typer.Argument(None, help="Record ID to display"),
    format_type: str = typer.Option("text", "--format", help="Output format: text (default) or json"),
) -> None:
    """Show details of a specific record."""
    try:
        config = get_global_config()
        client = APIClient(config.api_base_url, timeout_sec=config.timeout_sec)
        
        # Get record_id from argument or bound state
        if not record_id:
            from app.cli.lib.state_manager import get_state_value
            record_id = get_state_value("bound_record_id")
        
        if not record_id:
            safe_print_err(f"{emoji('❌', '[ERROR]')} 缺少 record_id. 用法: truthcast history show <record_id>")
            sys.exit(1)
        
        data = client.get(f"/history/{record_id}")
        
        if format_type == "json":
            safe_print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            _print_history_detail(data)
    
    except APIError as e:
        safe_print_err(f"\n{e.user_friendly_message()}")
        sys.exit(1)
    except Exception as e:
        safe_print_err(f"\n{emoji('❌', '[ERROR]')} 未知错误: {e}")
        sys.exit(1)


def _print_history_detail(data: dict) -> None:
    """Print formatted history detail."""
    record_id = data.get("record_id", "N/A")
    created_at = _format_timestamp(data.get("created_at", ""))
    risk_label = data.get("risk_label", "未知")
    risk_score = data.get("risk_score", 0)
    scenario = data.get("detected_scenario", "未识别")
    domains = data.get("evidence_domains", [])
    feedback = data.get("user_feedback", "无")
    
    safe_print(f"\n{emoji('📊', '[DETAIL]')} 分析记录详情\n")
    safe_print(f"  Record ID:     {record_id}")
    safe_print(f"  时间:         {created_at}")
    safe_print(f"  风险评估:      {_format_score(risk_label, risk_score)}")
    safe_print(f"  识别场景:      {scenario}")
    safe_print(f"  证据域:        {', '.join(domains) if domains else '无'}")
    safe_print(f"  用户反馈:      {feedback}")
    
    # Print summary if available
    if data.get("summary"):
        safe_print(f"\n  原始文本:")
        safe_print(f"    {data['summary'][:200]}...")
    
    safe_print("")


@history_app.command("feedback")
def submit_feedback(
    record_id: str = typer.Argument(..., help="Record ID"),
    feedback: str = typer.Option(..., "--feedback", "-f", help="Feedback: accurate/inaccurate"),
) -> None:
    """Submit feedback for a record."""
    try:
        config = get_global_config()
        client = APIClient(config.api_base_url, timeout_sec=config.timeout_sec)
        
        if feedback.lower() not in ["accurate", "inaccurate"]:
            safe_print_err(f"{emoji('❌', '[ERROR]')} 反馈必须是 'accurate' 或 'inaccurate'")
            sys.exit(1)
        
        response = client.post(f"/history/{record_id}/feedback", json={"feedback": feedback})
        
        if response.get("success"):
            safe_print(f"\n{emoji('✅', '[SUCCESS]')} 反馈已提交\n")
        else:
            safe_print_err(f"\n{emoji('❌', '[ERROR]')} 提交失败\n")
            sys.exit(1)
    
    except APIError as e:
        safe_print_err(f"\n{e.user_friendly_message()}")
        sys.exit(1)
    except Exception as e:
        safe_print_err(f"\n{emoji('❌', '[ERROR]')} 未知错误: {e}")
        sys.exit(1)


def history(
    subcommand: Optional[str] = typer.Argument(None),
) -> None:
    """History command (called by main CLI)."""
    # This is the entry point that typer will call
    pass
