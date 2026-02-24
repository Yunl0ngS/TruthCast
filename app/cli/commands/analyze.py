"""Analyze command - Full pipeline analysis."""

import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import typer

from app.cli.client import APIClient, APIError
from app.cli.lib.state_manager import update_state
from app.cli.lib.safe_output import emoji, safe_print, safe_print_err, decode_bytes
from app.cli._globals import get_global_config


def _read_input(file_path: Optional[str]) -> str:
    """
    Read input text from file or stdin.
    
    Args:
        file_path: Optional file path to read from
        
    Returns:
        Input text
    """
    if file_path:
        # Read from file
        try:
            path = Path(file_path)
            if not path.exists():
                safe_print_err(f"{emoji('❌', '[ERROR]')} 文件不存在: {file_path}")
                raise typer.Exit(1)
            
            text = path.read_text(encoding="utf-8")
            return text.strip()
        except Exception as e:
            safe_print_err(f"{emoji('❌', '[ERROR]')} 读取文件失败: {e}")
            raise typer.Exit(1)
    else:
        # Read from stdin
        if sys.stdin.isatty():
            safe_print_err(f"{emoji('💡', '[INFO]')} 提示: 请输入待分析文本 (Ctrl+D 结束输入):")
        
        try:
            if hasattr(sys.stdin, "buffer"):
                # Get raw bytes from stdin buffer to avoid encoding issues
                raw = sys.stdin.buffer.read()
                text = decode_bytes(raw)
            else:
                # Fallback to regular stdin
                text = sys.stdin.read()
            
            return text.strip()
        except KeyboardInterrupt:
            safe_print_err(f"\n{emoji('❌', '[ERROR]')} 用户中断")
            raise typer.Exit(1)


def _format_output(
    report_result: Dict[str, Any],
    format_type: str,
    markdown_exporter: Optional[Callable] = None,
) -> str:
    """
    Format analysis result for output.
    
    Args:
        report_result: Analysis result from pipeline
        format_type: Output format ('json' or 'markdown')
        markdown_exporter: Optional function to convert to markdown
        
    Returns:
        Formatted output string
    """
    if format_type == "json":
        return json.dumps(report_result, ensure_ascii=True, indent=2)
    elif format_type == "markdown" and markdown_exporter:
        return markdown_exporter(report_result)
    else:
        return json.dumps(report_result, ensure_ascii=True, indent=2)


def analyze(
    text: Optional[str] = typer.Argument(None, help="文本内容或文件路径"),
    file: Optional[str] = typer.Option(None, "--file", "-f", help="从文件读取内容"),
    format_type: str = typer.Option("json", "--format", help="输出格式: json (默认)"),
    local_agent: bool = typer.Option(False, "--local-agent", help="使用本地 Agent（无需后端）"),
    async_mode: bool = typer.Option(False, "--async", help="异步分析（立即返回 task_id，后台运行）"),
) -> None:
    """
    全链路分析：风险快照 -> 主张 -> 证据 -> 报告 -> 舆情预演
    """
    # Read input
    input_text = _read_input(file or text)
    if not input_text:
        safe_print_err(f"{emoji('❌', '[ERROR]')} 缺少输入文本")
        raise typer.Exit(1)
    
    # Get global config
    config = get_global_config()
    
    # Local agent mode
    if local_agent:
        try:
            from app.cli.local_agent import run_pipeline_locally
            
            result = run_pipeline_locally(input_text)
            output = _format_output(result, format_type)
            safe_print(output)
            
            # Save state
            if isinstance(result, dict) and "record_id" in result:
                update_state("last_record_id", result["record_id"])
        except Exception as e:
            safe_print_err(f"{emoji('❌', '[ERROR]')} 本地分析失败: {e}")
            raise typer.Exit(1)
    else:
        # Remote API mode
        try:
            api_client = APIClient(config.api_base_url, timeout_sec=config.timeout_sec)
            
            # Show progress
            safe_print_err(f"{emoji('🔍', '[1/4]')} 正在分析风险...")
            safe_print_err(f"{emoji('📋', '[2/4]')} 正在抽取主张...")
            safe_print_err(f"{emoji('🔎', '[3/4]')} 正在检索证据...")
            safe_print_err(f"{emoji('📊', '[4/4]')} 正在生成报告...")
            
            # Call API
            report_result = api_client.post("/detect/report", json={"text": input_text})
            
            # Format output
            output = _format_output(report_result, format_type)
            safe_print(output)
            
            # Save state
            if isinstance(report_result, dict) and "record_id" in report_result:
                update_state("last_record_id", report_result["record_id"])
        except APIError as e:
            safe_print_err(f"\n{e.user_friendly_message()}")
            raise typer.Exit(1)
        except Exception as e:
            safe_print_err(f"\n{emoji('❌', '[ERROR]')} 分析失败: {e}")
            raise typer.Exit(1)
