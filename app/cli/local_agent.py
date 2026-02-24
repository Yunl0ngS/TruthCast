"""Local agent mode for CLI REPL.

This is an optional mode that uses a local OpenAI-compatible LLM to decide
which CLI tools (backend API calls) to run.
"""

import json
import os
import sys
import time
from typing import Any, Optional
from urllib import error, request

import typer

from app.cli._globals import get_global_config
from app.cli.client import APIClient, APIError
from app.cli.commands.analyze import run_analysis_pipeline
from app.cli.lib.state_manager import update_state
from app.services.json_utils import safe_json_loads


def _llm_endpoint() -> str:
    base = (os.getenv("TRUTHCAST_LLM_BASE_URL") or "").strip()
    if not base:
        base = "https://api.openai.com/v1"
    base = base.rstrip("/")

    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def _llm_model() -> str:
    return (os.getenv("TRUTHCAST_LLM_MODEL") or "gpt-4o-mini").strip()


def _llm_api_key() -> str:
    return (os.getenv("TRUTHCAST_LLM_API_KEY") or "").strip()


def _call_llm(messages: list[dict[str, str]], timeout_sec: int) -> str:
    api_key = _llm_api_key()
    if not api_key:
        raise RuntimeError("Missing TRUTHCAST_LLM_API_KEY")

    url = _llm_endpoint()
    payload = {
        "model": _llm_model(),
        "messages": messages,
        "temperature": 0.2,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    req = request.Request(url=url, method="POST", data=body, headers=headers)

    try:
        with request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else str(e)
        raise RuntimeError(f"LLM HTTPError {e.code}: {raw}")
    except Exception as e:
        raise RuntimeError(f"LLM request failed: {e}")

    try:
        data = json.loads(raw)
        return data["choices"][0]["message"]["content"]
    except Exception:
        return raw


def _system_prompt() -> str:
    return (
        "You are a local CLI agent for TruthCast.\n"
        "Decide whether to call a tool or respond normally.\n\n"
        "Available tools:\n"
        "- analyze: Run the full backend analysis pipeline for a given text\n\n"
        "Return STRICT JSON ONLY (no markdown).\n"
        "Schema:\n"
        "- Tool call: {\"action\":\"tool\",\"tool\":\"analyze\",\"args\":{\"text\":\"...\"}}\n"
        "- Final answer: {\"action\":\"final\",\"content\":\"...\"}\n"
    )


def _plan(user_text: str, timeout_sec: int) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": _system_prompt()},
        {"role": "user", "content": user_text},
    ]
    content = _call_llm(messages, timeout_sec=timeout_sec)
    parsed = safe_json_loads(content, context="cli.local_agent.plan")
    if parsed is None:
        return {"action": "final", "content": content}
    return parsed


def _read_multiline() -> Optional[str]:
    typer.echo("\n[多行输入] 粘贴/输入多行文本，用 '.' / 'EOF' / /send 发送，/cancel 取消\n")
    lines: list[str] = []
    while True:
        sys.stdout.write("... ")
        sys.stdout.flush()
        raw = sys.stdin.readline()
        if raw == "":
            raise EOFError

        line = raw.rstrip("\r\n")
        token = line.strip()
        if token in {".", "EOF", "/send"}:
            break
        if token in {"/cancel"}:
            return None
        if token.lower() in {"/exit", "quit", "exit"}:
            raise EOFError
        lines.append(line)

    return "\n".join(lines).rstrip("\n")


def _print_help() -> None:
    typer.echo("\n[Local Agent REPL]\n")
    typer.echo("  • 单行：直接输入并回车")
    typer.echo("  • 多行分析：/paste (结束: '.' / 'EOF' / /send)")
    typer.echo("  • 退出：/exit、quit、Ctrl+D")
    typer.echo("  • 注意：需要配置 TRUTHCAST_LLM_API_KEY/TRUTHCAST_LLM_BASE_URL/TRUTHCAST_LLM_MODEL\n")


def run_local_agent_repl() -> None:
    """Run a local-agent REPL.

    This mode calls a local LLM to decide whether to execute tools.
    """
    config = get_global_config()
    typer.echo("=" * 60)
    typer.echo("TruthCast REPL (Local Agent Mode)")
    typer.echo("=" * 60)
    typer.echo("输入 /help 查看帮助；输入 /exit 退出。\n")

    client = APIClient(
        base_url=config.api_base,
        timeout=config.timeout,
        retry_times=config.retry_times,
    )

    try:
        while True:
            try:
                raw = input("You: ").strip()
                if not raw:
                    continue

                if raw.lower() in {"/exit", "quit", "exit"}:
                    typer.echo("\n[✓] 已退出")
                    return
                if raw.startswith("/"):
                    cmd = raw.split()[0].lower()
                    if cmd == "/help":
                        _print_help()
                        continue
                    if cmd == "/paste":
                        msg = _read_multiline()
                        if not msg:
                            continue
                        raw = msg

                plan = _plan(raw, timeout_sec=config.timeout)
                action = str(plan.get("action", "final")).strip().lower()

                if action == "tool" and str(plan.get("tool", "")).strip().lower() == "analyze":
                    args = plan.get("args") or {}
                    if not isinstance(args, dict):
                        args = {}
                    text = args.get("text")
                    if not isinstance(text, str) or not text.strip():
                        text = raw

                    typer.echo("\n[agent] calling tool: analyze\n")
                    outputs = run_analysis_pipeline(client, text)
                    report_result = outputs.get("report") or {}

                    record_id = report_result.get("record_id")
                    if record_id:
                        update_state("bound_record_id", record_id)
                        update_state("last_record_id", record_id)

                    report = report_result.get("report") or report_result
                    conclusion = ""
                    if isinstance(report, dict):
                        conclusion = str(report.get("conclusion") or report.get("summary") or "").strip()
                    if conclusion:
                        typer.echo(f"\n[conclusion]\n{conclusion}\n")
                    else:
                        typer.echo(json.dumps(report_result, ensure_ascii=False, indent=2))
                    continue

                # Default: print final content
                content = plan.get("content")
                if not isinstance(content, str):
                    content = json.dumps(plan, ensure_ascii=False, indent=2)
                typer.echo(f"\n{content}\n")

            except EOFError:
                typer.echo("\n\n[✓] 已退出")
                return
            except KeyboardInterrupt:
                typer.echo("\n\n[✓] 已退出")
                return
            except APIError as e:
                typer.echo(e.user_friendly_message(), err=True)
            except Exception as e:
                typer.echo(f"❌ local-agent error: {e}", err=True)
                time.sleep(0.2)
    finally:
        client.close()
