"""REPL command - interactive mode with optional local agent."""

from typing import Optional

import typer

from app.cli._globals import get_global_config
from app.cli.commands import chat
from app.cli.local_agent import run_local_agent_repl


def repl(
    session_id: Optional[str] = typer.Option(
        None,
        "--session-id",
        "-s",
        help="Session ID for continuing an existing backend chat conversation",
    ),
) -> None:
    """Interactive REPL.

    - Default: backend chat REPL (same as `truthcast chat`)
    - With `--local-agent`: local LLM agent decides which CLI tools to call
    """
    config = get_global_config()
    if config.local_agent:
        run_local_agent_repl()
        return

    chat.chat(session_id=session_id)
