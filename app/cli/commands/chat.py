"""Chat command - Interactive conversation mode."""

import typer

def chat(
    session_id: str = typer.Option(
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
    """
    typer.echo("TODO: Chat mode functionality to be implemented")
    if session_id:
        typer.echo(f"  Session ID: {session_id}")
