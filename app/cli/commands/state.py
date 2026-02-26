"""State command - Pipeline state and record binding management."""

import sys
from typing import Optional

import typer

from app.cli.lib.state_manager import get_state_value, load_state, save_state, update_state
from app.cli.lib.safe_output import safe_print, safe_print_err, emoji

state_app = typer.Typer(help="Manage state and bound records")


@state_app.command("bind")
def bind_record(
    record_id: str = typer.Argument(..., help="Record ID to bind"),
) -> None:
    """Bind a record ID to local state for convenient access.
    
    Once bound, subsequent commands can use the bound record_id without
    explicitly specifying --record-id parameter.
    
    Example:
        truthcast bind rec_abc123
        truthcast show  # Uses bound rec_abc123
    """
    if not record_id or len(record_id) < 3:
        safe_print_err(f"{emoji('❌', '[ERROR]')} 错误: record_id 应该至少包含 3 个字符\n")
        sys.exit(1)
    
    try:
        update_state("bound_record_id", record_id)
        safe_print_err(f"\n{emoji('✅', '[SUCCESS]')} 已绑定 record_id: {record_id}\n")
        safe_print(f"{emoji('💡', '[INFO]')} 提示: 后续命令可使用绑定的记录，无需重复指定 record_id\n")
    except Exception as e:
        safe_print(f"\n{emoji('❌', '[ERROR]')} 绑定失败: {e}\n")
        sys.exit(1)


@state_app.command("show")
def show_state() -> None:
    """Show current local state."""
    state = load_state()
    
    if not state:
        safe_print(f"\n{emoji('📭', '[EMPTY]')} 本地状态为空\n")
        return
    
    safe_print(f"\n{emoji('📋', '[INFO]')} 本地状态:\n")
    for key, value in state.items():
        safe_print(f"  {key}: {value}")
    safe_print("")


@state_app.command("clear")
def clear_state(
    confirm: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation and clear immediately",
    ),
) -> None:
    """Clear all local state."""
    if not confirm:
        safe_print_err(f"{emoji('⚠️', '[WARN]')}  这将清除所有本地状态（包括绑定的 record_id）")
        response = typer.confirm("确实要继续吗?")
        if not response:
            safe_print(f"{emoji('✓', '[OK]')} 已取消")
            return
    
    try:
        save_state({})
        safe_print(f"\n{emoji('✅', '[SUCCESS]')} 已清除所有本地状态\n")
    except Exception as e:
        safe_print(f"\n{emoji('❌', '[ERROR]')} 清除失败: {e}\n")
        sys.exit(1)


def state(
    action: str = typer.Argument(
        "show",
        help="Action: bind, show, clear, reset",
    ),
    record_id: Optional[str] = typer.Argument(
        None,
        help="Record ID (required for bind action)",
    ),
) -> None:
    """Manage local state and record bindings.
    
    This command handles local state management, including:
    - bind: Bind a record_id for convenient access
    - show: Display current state
    - clear/reset: Clear all state
    
    Examples:
        truthcast state bind rec_abc123
        truthcast state show
        truthcast state clear
        truthcast state reset
    """
    if action == "bind":
        if not record_id:
            safe_print_err(f"{emoji('❌', '[ERROR]')} 错误: 'bind' 操作需要提供 record_id\n")
            safe_print_err("用法: truthcast state bind <record_id>")
            sys.exit(1)
        bind_record(record_id=record_id)
    elif action == "show":
        show_state()
    elif action in {"clear", "reset"}:
        clear_state()
    else:
        safe_print(
            f"{emoji('❌', '[ERROR]')} 未知操作: {action}\n\n"
            f"支持的操作: bind, show, clear, reset\n",
            err=True,
        )
        sys.exit(1)
