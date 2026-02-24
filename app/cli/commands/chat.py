"""Chat command - Interactive conversation mode."""

import atexit
import datetime
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict, Generator, Optional

import httpx
import typer

from app.cli.client import APIClient, APIError, TimeoutError as APITimeoutError
from app.cli.lib.state_manager import get_state_value, update_state
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


def _normalize_input_text(text: str) -> str:
    """Normalize console input to UTF-8-safe text."""
    if not text:
        return text

    has_surrogate = any(0xD800 <= ord(ch) <= 0xDFFF for ch in text)
    if not has_surrogate:
        return text

    stdin_encoding = sys.stdin.encoding or "utf-8"
    try:
        raw = text.encode(stdin_encoding, errors="surrogateescape")
    except Exception:
        raw = text.encode("utf-8", errors="replace")

    for encoding in ("utf-8", "gb18030", stdin_encoding):
        try:
            candidate = raw.decode(encoding)
            return candidate.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
        except UnicodeDecodeError:
            continue

    return raw.decode("utf-8", errors="replace")


def _drain_buffered_stdin_lines(max_wait_ms: int = 180) -> list[str]:
    """Read already-buffered pasted lines from stdin without blocking for long."""
    if not sys.stdin.isatty():
        return []

    lines: list[str] = []
    wait_seconds = max(0.01, max_wait_ms / 1000.0)

    if os.name == "nt":
        try:
            import msvcrt
        except Exception:
            return []

        end_time = time.monotonic() + wait_seconds
        current: list[str] = []

        while time.monotonic() < end_time:
            saw_input = False
            while msvcrt.kbhit():
                saw_input = True
                ch = msvcrt.getwch()

                if ch in {"\r", "\n"}:
                    lines.append("".join(current))
                    current = []
                    end_time = time.monotonic() + wait_seconds
                    continue

                if ch in {"\x00", "\xe0"}:
                    if msvcrt.kbhit():
                        msvcrt.getwch()
                    continue

                if ch in {"\b", "\x7f"}:
                    if current:
                        current.pop()
                    continue

                current.append(ch)
                end_time = time.monotonic() + wait_seconds

            if not saw_input:
                time.sleep(0.005)

        if current:
            lines.append("".join(current))
        return lines

    try:
        import select
    except Exception:
        return []

    end_time = time.monotonic() + wait_seconds
    while time.monotonic() < end_time:
        remaining = max(0.0, end_time - time.monotonic())
        readable, _, _ = select.select([sys.stdin], [], [], remaining)
        if not readable:
            break

        raw = sys.stdin.readline()
        if raw == "":
            break

        lines.append(raw.rstrip("\r\n"))
        end_time = time.monotonic() + wait_seconds

    return lines


def _merge_plain_text_with_buffer(first_line: str) -> tuple[str, list[str]]:
    """Merge first plain-text line with quickly pasted following lines."""
    merged_lines = [_normalize_input_text(first_line)]
    pending_inputs: list[str] = []

    for extra in _drain_buffered_stdin_lines():
        normalized = _normalize_input_text(extra)
        stripped = normalized.strip()

        if not stripped:
            merged_lines.append("")
            continue

        if stripped.startswith("/"):
            pending_inputs.append(normalized)
            continue

        merged_lines.append(normalized)

    merged_text = "\n".join(merged_lines).strip()
    return merged_text, pending_inputs



def parse_sse_line(line: str) -> Optional[Dict[str, Any]]:
    """
    Parse a single SSE line.
    
    Args:
        line: Raw SSE line (e.g., "data: {...}")
    
    Returns:
        Parsed event dict or None if not a data line
    """
    if not line.strip():
        return None
    
    if not line.startswith("data:"):
        return None
    
    # Strip "data: " prefix
    json_str = line[5:].strip()
    # Normalize potential surrogate chars from terminal/stream decoding.
    json_str = json_str.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, UnicodeEncodeError, ValueError):
        return None


def stream_chat_message(
    client: APIClient, session_id: str, user_input: str
) -> Generator[Dict[str, Any], None, None]:
    """
    Stream chat message to backend and yield SSE events.
    
    Args:
        client: API client instance
        session_id: Chat session ID
        user_input: User message text
    
    Yields:
        Parsed SSE event dicts
    """
    path = f"/chat/sessions/{session_id}/messages/stream"
    payload = {"text": user_input}
    
    try:
        ctx_mgr = client.stream("POST", path, json=payload)

        with ctx_mgr as response:
            for line in response.iter_lines():
                if isinstance(line, bytes):
                    line = line.decode("utf-8", errors="replace")
                else:
                    line = line.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
                
                event = parse_sse_line(line)
                if event:
                    yield event
    except httpx.TimeoutException as e:
        raise APITimeoutError("SSE stream timed out while waiting for server events") from e
    except httpx.HTTPError as e:
        raise APIError(f"SSE stream HTTP error: {e}") from e
    except APIError:
        raise


def render_token(content: str) -> None:
    """Render a token (incremental content) without newline."""
    print(content, end="", flush=True)


def render_stage(stage: str, status: str) -> None:
    """Render a stage update."""
    stage_emoji = {
        "risk": _emoji("🔍", "[RISK]"),
        "claims": _emoji("📋", "[CLAIMS]"),
        "evidence_search": _emoji("🌐", "[SEARCH]"),
        "evidence_align": _emoji("🔗", "[ALIGN]"),
        "report": _emoji("📊", "[REPORT]"),
        "simulation": _emoji("🎭", "[SIM]"),
        "content": _emoji("✍️", "[WRITE]"),
    }
    
    status_emoji = {
        "running": _emoji("⏳", "[LOADING]"),
        "done": _emoji("✅", "[DONE]"),
        "failed": _emoji("❌", "[FAILED]"),
    }
    
    stage_name = {
        "risk": "风险快照",
        "claims": "主张抽取",
        "evidence_search": "证据检索",
        "evidence_align": "证据对齐",
        "report": "综合报告",
        "simulation": "舆情预演",
        "content": "应对内容",
    }
    
    emoji = stage_emoji.get(stage, _emoji("📌", "[MARK]"))
    status_mark = status_emoji.get(status, "")
    name = stage_name.get(stage, stage)
    
    if status == "running":
        print(f"\n{emoji} {name}中...")
    elif status == "done":
        print(f"{status_mark} {name}完成")


def render_message(message: Dict[str, Any]) -> None:
    """Render a complete message with actions and references."""
    content = message.get("content", "")
    actions = message.get("actions", [])
    references = message.get("references", [])
    
    # Print main content
    if content:
        print(f"\n{content}")
    
    # Print actions
    if actions:
        print("\n[相关操作]")
        for action in actions:
            label = action.get("label", "")
            command = action.get("command", "")
            href = action.get("href", "")
            
            if command:
                print(f"  - {label}: {command}")
            elif href:
                print(f"  - {label}: {href}")
    
    # Print references
    if references:
        print("\n[参考链接]")
        for ref in references[:5]:  # Limit to 5
            title = ref.get("title", "")
            href = ref.get("href", "")
            description = ref.get("description", "")
            
            print(f"  - {title}")
            if href:
                print(f"    {href}")
            if description:
                print(f"    {description}")


def render_error(error_msg: str) -> None:
    """Render an error message."""
    print(f"\n{_emoji('❌', '[ERROR]')} 错误: {error_msg}")


def handle_sse_stream(
    client: APIClient, session_id: str, user_input: str
) -> None:
    """
    Handle SSE stream and render events.
    
    Args:
        client: API client instance
        session_id: Chat session ID
        user_input: User message text
    """
    user_input = _normalize_input_text(user_input)
    log_fp = _open_cli_evidence_log(session_id=session_id)

    token_buf: str = ""
    last_flush = time.monotonic()
    flush_interval_sec = 0.05
    flush_chars = 48

    def _flush_tokens(force_newline: bool = False) -> None:
        nonlocal token_buf, last_flush
        if token_buf:
            render_token(token_buf)
            _log_line(log_fp, f"[token] {token_buf}")
            token_buf = ""
            last_flush = time.monotonic()
        if force_newline:
            print()

    try:
        _log_line(log_fp, f"[session] {session_id}")
        _log_line(log_fp, f"[user] {user_input}")

        for event in stream_chat_message(client, session_id, user_input):
            event_type = event.get("type")
            data = event.get("data", {})

            if event_type == "token":
                content = data.get("content", "")
                if content:
                    token_buf += content

                now = time.monotonic()
                if len(token_buf) >= flush_chars or (token_buf and (now - last_flush) >= flush_interval_sec):
                    _flush_tokens()

            elif event_type == "stage":
                _flush_tokens(force_newline=True)
                stage = data.get("stage", "")
                status = data.get("status", "")
                render_stage(stage, status)
                _log_line(log_fp, f"[stage] {stage} {status}")

            elif event_type == "message":
                _flush_tokens(force_newline=True)
                message = data.get("message", {})
                render_message(message)

                content = message.get("content", "")
                actions = message.get("actions", [])
                references = message.get("references", [])
                if content:
                    _log_line(log_fp, f"[message] {content}")
                if actions:
                    _log_line(log_fp, f"[actions] {actions}")
                if references:
                    _log_line(log_fp, f"[references] {references[:10]}")

            elif event_type == "error":
                _flush_tokens(force_newline=True)
                error_msg = data.get("message", "Unknown error")
                render_error(error_msg)
                _log_line(log_fp, f"[error] {error_msg}")

            elif event_type == "done":
                _flush_tokens(force_newline=True)
                _log_line(log_fp, "[done]")
                break

    except APIError as e:
        _flush_tokens(force_newline=True)
        _log_line(log_fp, f"[api_error] {e}")
        print(f"\n{e.user_friendly_message()}", file=sys.stderr)
    except Exception as e:
        _flush_tokens(force_newline=True)
        _log_line(log_fp, f"[unexpected_error] {e}")
        print(f"\n{_emoji('❌', '[ERROR]')} 意外错误: {e}", file=sys.stderr)
    finally:
        try:
            if log_fp is not None:
                log_fp.close()
        except Exception:
            pass


def create_session(client: APIClient) -> Optional[str]:
    """
    Create a new chat session.
    
    Args:
        client: API client instance
    
    Returns:
        Session ID or None if failed
    """
    try:
        response = client.post("/chat/sessions", json={})
        return response.get("session_id")
    except APIError as e:
        print(f"\n{e.user_friendly_message()}", file=sys.stderr)
        return None


def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully."""
    print("\n\n[EXIT] 已退出对话模式", file=sys.stderr)
    sys.exit(0)


def _get_cli_data_dir() -> Path:
    """Get TruthCast CLI data dir (shared with state.json)."""
    if os.name == "nt":
        app_data = os.getenv("APPDATA")
        if app_data:
            state_dir = Path(app_data) / "truthcast"
        else:
            state_dir = Path.home() / ".truthcast"
    else:
        state_dir = Path.home() / ".truthcast"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def _find_repo_sisyphus_dir() -> Optional[Path]:
    """Find a `.sisyphus` directory by walking up from this file.

    Returns None if not found (e.g., installed package usage).
    """
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / ".sisyphus"
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def _open_cli_evidence_log(session_id: str):
    """Open a per-session evidence log file (best-effort)."""
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_sid = (session_id or "unknown")[:12]

    base = _find_repo_sisyphus_dir()
    if base is not None:
        log_dir = base / "evidence" / "cli"
    else:
        log_dir = _get_cli_data_dir() / "evidence" / "cli"

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{ts}-{safe_sid}.log"
        return open(log_path, "a", encoding="utf-8")
    except Exception:
        return None


def _log_line(fp, line: str) -> None:
    if fp is None:
        return
    try:
        fp.write(line.replace("\r", "\\r") + "\n")
        fp.flush()
    except Exception:
        return


def _try_enable_readline_history() -> None:
    """Enable Up/Down history if readline is available (best-effort)."""
    try:
        import readline  # type: ignore
    except Exception:
        return

    history_file = _get_cli_data_dir() / "chat_history"

    read_history_file = getattr(readline, "read_history_file", None)
    if callable(read_history_file):
        try:
            read_history_file(str(history_file))
        except FileNotFoundError:
            pass
        except OSError:
            # e.g. permission issues
            pass

    set_history_length = getattr(readline, "set_history_length", None)
    if callable(set_history_length):
        try:
            set_history_length(1000)
        except Exception:
            pass

    def _save_history() -> None:
        write_history_file = getattr(readline, "write_history_file", None)
        if not callable(write_history_file):
            return
        try:
            write_history_file(str(history_file))
        except Exception:
            return

    atexit.register(_save_history)


def _print_repl_help() -> None:
    print("\n[REPL 帮助]\n")
    print("  - 单行长文本：直接输入并回车，自动按 /analyze 发起检测")
    print("  - 粘贴多行文本：自动合并连续粘贴行后再检测")
    print("  - 多行分析：输入 /paste 粘贴多行文本（默认作为 /analyze 发送）")
    print("  - 多行消息：输入 /multiline 粘贴多行文本（作为普通消息发送）")
    print("    - 结束并发送：输入单独一行 '.' 或 'EOF'，或输入 /send")
    print("    - 取消：输入 /cancel")
    print("  - 退出：/exit、quit、Ctrl+D")
    print("  - 发送以 '/' 开头的普通文本：使用 '//' 开头（会自动去掉一个 '/'）")
    print("  - 其他以 / 开头的命令会原样发送到后端执行（不在本地做参数校验）\n")


def _read_multiline_message() -> Optional[str]:
    """Read a paste-friendly multiline message.

    Returns:
        - str: message to send
        - None: cancelled

    Raises:
        EOFError: if stdin is closed (Ctrl+D / Ctrl+Z)
    """
    print("\n[多行输入模式] 粘贴/输入多行内容，然后用 '.' / 'EOF' / /send 发送，/cancel 取消")
    lines = []
    while True:
        # Do not use input() here: avoid prompt spam when pasting many lines.
        print("... ", end="", flush=True)
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
            # Treat exit inside multiline as an exit from REPL.
            raise EOFError

        lines.append(line)

    text = "\n".join(lines).rstrip("\n")
    return text


def chat(
    session_id: Optional[str] = typer.Option(
        None,
        "--session-id",
        "-s",
        help="Session ID for continuing an existing conversation"
    )
) -> None:
    """
    Interactive chat mode for multi-turn conversations.
    
    Supports commands like:
    - /analyze <text>: Analyze news content
    - /why: Ask for explanation
    - /compare: Compare two analysis records
    - /help: Show available commands
    - /exit or quit: Exit chat mode
    """
    # Register Ctrl+C handler
    signal.signal(signal.SIGINT, signal_handler)
    config = get_global_config()

    # Best-effort local input history (Up/Down)
    _try_enable_readline_history()
    
    # Initialize API client
    client = APIClient(
        base_url=config.api_base,
        timeout=config.timeout,
        retry_times=config.retry_times,
    )
    
    # Get or create session
    if not session_id:
        # Try to load last session from state
        session_id = get_state_value("last_session_id") or None
    
    if not session_id:
        # Create new session
        print(_emoji("🔄", "[LOADING]") + " 创建新会话...")
        session_id = create_session(client)
        if not session_id:
            print(_emoji("❌", "[ERROR]") + " 无法创建会话", file=sys.stderr)
            raise typer.Exit(1)

        print(f"{_emoji('✅', '[SUCCESS]')} 会话已创建: {session_id}\n")
    else:
        print(f"{_emoji('🔄', '[LOADING]')} 使用会话: {session_id}\n")

    # Persist the chosen session_id for next time
    assert session_id is not None
    update_state("last_session_id", session_id)
    
    # Welcome message
    print("=" * 60)
    print("TruthCast 对话工作台 - 交互式分析模式")
    print("=" * 60)
    print()
    print(_emoji('💡', '[TIP]') + " 提示:")
    print("  - 输入 /help 查看可用命令")
    print("  - 直接输入文本即可自动检测（等价于 /analyze <文本>）")
    print("  - 粘贴多行文本会自动合并后检测")
    print("  - 仍可使用 /analyze <文本> 手动触发")
    print("  - 输入 /exit 或 quit 退出")
    print()
    print("=" * 60)
    print()
    
    # REPL loop
    pending_inputs: list[str] = []
    while True:
        try:
            # Get user input (single-line by default)
            if pending_inputs:
                raw_input = _normalize_input_text(pending_inputs.pop(0)).strip()
                print(f"You: {raw_input}")
            else:
                raw_input = _normalize_input_text(input("You: ")).strip()

            if not raw_input:
                continue

            # Exit commands (work even without leading '/')
            if raw_input.lower() in {"/exit", "quit", "exit"}:
                print("\n[EXIT] 已退出对话模式")
                break

            # Allow sending a literal leading '/'
            if raw_input.startswith("//"):
                user_input = _normalize_input_text(raw_input[1:])
                print()  # Blank line before assistant response
                handle_sse_stream(client, session_id, user_input)
                print()  # Blank line after response
                continue

            # Local REPL commands (routing: leading '/' => command)
            if raw_input.startswith("/"):
                cmd = raw_input.split()[0].lower()

                if cmd == "/help":
                    _print_repl_help()
                    continue

                if cmd in {"/paste", "/multiline"}:
                    try:
                        msg = _read_multiline_message()
                    except EOFError:
                        print("\n\n[EXIT] 已退出对话模式")
                        break

                    if not msg:
                        continue

                    if cmd == "/paste":
                        user_input = f"/analyze {_normalize_input_text(msg)}"
                    else:
                        user_input = _normalize_input_text(msg)
                elif cmd == "/send":
                    # /send only makes sense inside multiline mode
                    print("\n提示: /send 用于多行输入模式的结束与发送；请先输入 /paste 或 /multiline\n")
                    continue
                else:
                    # Forward other slash-commands to backend as-is.
                    user_input = _normalize_input_text(raw_input)
            else:
                merged_text, buffered_commands = _merge_plain_text_with_buffer(raw_input)
                if buffered_commands:
                    pending_inputs.extend(buffered_commands)

                # Plain text is treated as analyze input by default.
                user_input = f"/analyze {merged_text}"

            # Send to backend and stream response
            print()  # Blank line before assistant response
            handle_sse_stream(client, session_id, user_input)
            print()  # Blank line after response
        
        except EOFError:
            # Handle Ctrl+D (Unix) or Ctrl+Z (Windows)
            print("\n\n[EXIT] 已退出对话模式")
            break
    
    # Clean exit
    client.close()
