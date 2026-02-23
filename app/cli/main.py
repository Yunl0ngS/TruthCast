"""
TruthCast CLI Main Entry Point

Provides command-line interface for fake news detection, opinion simulation,
and content generation.
"""

import sys
from pathlib import Path

import typer

# Load project environment variables immediately upon module import
from app.core.env_loader import load_project_env

# Initialize environment before any other imports that depend on it
load_project_env()

# Now safe to import the rest
from app.cli.commands import analyze, chat, content, export, history, simulate, state

app = typer.Typer(
    name="truthcast",
    help="TruthCast: Fake news detection + opinion simulation intelligent system",
    no_args_is_help=True,
)

# Register command groups
app.command()(chat.chat)
app.command()(analyze.analyze)
app.command()(simulate.simulate)
app.command()(history.history)
app.command()(content.content)
app.command()(export.export_cmd)
app.command()(state.state)


def main() -> None:
    """Main entry point for CLI."""
    try:
        app()
    except KeyboardInterrupt:
        print("\n[✓] Aborted by user.", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f"\n[✗] Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
