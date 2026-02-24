"""Analyze command - Full pipeline analysis."""

import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import typer

from app.cli.client import APIClient, APIError
from app.cli.lib.state_manager import update_state
from app.cli._globals import get_global_config


# Detect if console supports unicode/emoji
def _supports_unicode() -> bool:
    """Check if console supports unicode output."""
    try:
        # Try encoding a test emoji
        "\u2705".encode(sys.stdout.encoding or 'utf-8')
        return True
    except (UnicodeEncodeError, LookupError):
        return False


_UNICODE_SUPPORT = _supports_unicode()


def _emoji(unicode_char: str, ascii_fallback: str) -> str:
    """Return emoji if supported, otherwise ASCII fallback."""
    return unicode_char if _UNICODE_SUPPORT else ascii_fallback


def _safe_print(text: str) -> None:
    """Print text with terminal-encoding fallback."""
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        sanitized = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(sanitized)


def _safe_error(text: str) -> None:
    """Print error text with terminal-encoding fallback."""
    try:
        typer.echo(text, err=True)
    except UnicodeEncodeError:
        encoding = sys.stderr.encoding or "utf-8"
        sanitized = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        typer.echo(sanitized, err=True)


def _decode_stdin_bytes(raw: bytes) -> str:
    """Decode stdin bytes with best-effort fallback."""
    candidates = [
        "utf-8",
        getattr(sys.stdin, "encoding", None),
        "gb18030",
    ]
    for encoding in candidates:
        if not encoding:
            continue
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


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
                typer.echo(f"{_emoji('❌', '[ERROR]')} 文件不存在: {file_path}", err=True)
                raise typer.Exit(1)
            
            text = path.read_text(encoding="utf-8")
            return text.strip()
        except Exception as e:
            typer.echo(f"{_emoji('❌', '[ERROR]')} 读取文件失败: {e}", err=True)
            raise typer.Exit(1)
    else:
        # Read from stdin
        if sys.stdin.isatty():
            typer.echo(f"{_emoji('💡', '[INFO]')} 提示: 请输入待分析文本 (Ctrl+D 结束输入):", err=True)
        
        try:
            if hasattr(sys.stdin, "buffer"):
                text = _decode_stdin_bytes(sys.stdin.buffer.read())
            else:
                text = sys.stdin.read()
            return text.strip()
        except KeyboardInterrupt:
            typer.echo(f"\n{_emoji('❌', '[ERROR]')} 用户中断", err=True)
            raise typer.Exit(0)


def _format_text_output(result: Dict[str, Any]) -> str:
    """
    Format analysis result as human-readable text.
    
    Args:
        result: Complete analysis result from /detect/report
        
    Returns:
        Formatted text output
    """
    lines = []
    
    # Header
    lines.append(f"{_emoji('✅', '[SUCCESS]')} 分析完成\n")
    
    # Risk assessment
    risk_label = result.get("risk_label", "未知")
    risk_score = result.get("risk_score", 0)
    lines.append(f"风险评估: {risk_label} (风险分数: {risk_score}/100)")
    
    # Claims and evidence count
    claim_reports = result.get("claim_reports", [])
    total_claims = len(claim_reports)
    
    # Count total evidences
    total_evidences = 0
    for claim_report in claim_reports:
        total_evidences += len(claim_report.get("evidences", []))
    
    lines.append(f"主张数量: {total_claims} 条")
    lines.append(f"证据数量: {total_evidences} 条")
    
    # Record ID (if present)
    record_id = result.get("record_id")
    if record_id:
        lines.append(f"记录ID: {record_id}")
    
    lines.append("")
    
    # Summary
    summary = result.get("summary", "")
    if summary:
        lines.append("[综合结论]")
        lines.append(summary)
        lines.append("")
    
    # Suspicious points
    suspicious_points = result.get("suspicious_points", [])
    if suspicious_points:
        lines.append("[可疑点]")
        for i, point in enumerate(suspicious_points, 1):
            lines.append(f"  {i}. {point}")
        lines.append("")
    
    # Detected scenario and evidence domains
    detected_scenario = result.get("detected_scenario")
    evidence_domains = result.get("evidence_domains", [])
    
    if detected_scenario:
        lines.append(f"[识别场景] {detected_scenario}")
    
    if evidence_domains:
        domains_str = ", ".join(evidence_domains)
        lines.append(f"[证据覆盖域] {domains_str}")
    
    return "\n".join(lines)


def run_analysis_pipeline(
    client: APIClient,
    text: str,
    *,
    on_stage: Callable[[str], None] | None = None,
) -> Dict[str, Any]:
    """Run the backend analysis pipeline and return all intermediate outputs."""

    def _stage(name: str) -> None:
        if on_stage is not None:
            on_stage(name)

    _stage("risk")
    detect_result = client.post("/detect", json={"text": text})

    _stage("claims")
    claims_result = client.post("/detect/claims", json={"text": text})
    claims = claims_result.get("claims", [])

    _stage("evidence")
    evidence_result = client.post(
        "/detect/evidence",
        json={"text": text, "claims": claims},
    )
    evidences = evidence_result.get("evidences", [])

    _stage("report")
    report_result = client.post(
        "/detect/report",
        json={
            "text": text,
            "claims": claims,
            "evidences": evidences,
            "detect_data": {
                "label": detect_result.get("label"),
                "confidence": detect_result.get("confidence"),
                "score": detect_result.get("score"),
                "reasons": detect_result.get("reasons"),
            },
        },
    )

    return {
        "detect": detect_result,
        "claims": claims_result,
        "evidence": evidence_result,
        "report": report_result,
    }


def analyze(
    file: Optional[str] = typer.Option(
        None,
        "-f",
        "--file",
        help="Input file path (if omitted, read from stdin)",
    ),
) -> None:
    """
    Run the full analysis pipeline.

    Steps:
    - Risk snapshot (/detect)
    - Claims extraction (/detect/claims)
    - Evidence retrieval (/detect/evidence)
    - Report generation (/detect/report)

    Output defaults to human-readable text; use global `--json` for JSON.

    Examples:
      truthcast analyze -f news.txt
      cat news.txt | truthcast analyze
      truthcast --json analyze -f news.txt
    """
    config = get_global_config()
    
    # Read input
    try:
        text = _read_input(file)
    except typer.Exit:
        raise
    
    if not text:
        _safe_error(f"{_emoji('❌', '[ERROR]')} 输入为空")
        raise typer.Exit(1)
    
    # Create API client
    client = APIClient(
        base_url=config.api_base,
        timeout=config.timeout,
        retry_times=config.retry_times,
    )
    
    try:
        def _on_stage(stage: str) -> None:
            if config.output_format == "json":
                return
            if stage == "risk":
                typer.echo(f"{_emoji('🔍', '[1/4]')} 正在分析风险...", err=True)
            elif stage == "claims":
                typer.echo(f"{_emoji('📋', '[2/4]')} 正在抽取主张...", err=True)
            elif stage == "evidence":
                typer.echo(f"{_emoji('🔎', '[3/4]')} 正在检索证据...", err=True)
            elif stage == "report":
                typer.echo(f"{_emoji('📊', '[4/4]')} 正在生成报告...", err=True)

        outputs = run_analysis_pipeline(client, text, on_stage=_on_stage)
        report_result = outputs["report"]
        
        # Save record_id to state if present
        record_id = report_result.get("record_id")
        if record_id:
            update_state("last_record_id", record_id)
            update_state("last_api_base", config.api_base)
        
        # Output result
        if config.output_format == "json":
            # JSON output to stdout
            _safe_print(json.dumps(report_result, ensure_ascii=True, indent=2))
        else:
            # Human-readable text output
            output = _format_text_output(report_result)
            _safe_print(output)
        
    except APIError as e:
        _safe_error(e.user_friendly_message())
        raise typer.Exit(1)
    except KeyboardInterrupt:
        _safe_error(f"\n{_emoji('❌', '[ERROR]')} 用户中断")
        raise typer.Exit(0)
    except Exception as e:
        _safe_error(f"{_emoji('❌', '[ERROR]')} 未知错误: {e}")
        raise typer.Exit(1)
    finally:
        client.close()
