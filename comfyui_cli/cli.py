"""ComfyUI CLI - main entry point."""

from __future__ import annotations

import typer
from rich.console import Console

from . import __version__
from .commands import models, queue, run, system

app = typer.Typer(
    name="comfyui",
    help="CLI tool for ComfyUI - manage workflows, models, and generation from your terminal.",
    no_args_is_help=True,
)
console = Console()

# Register subcommands
app.add_typer(system.app, name="status", help="Server status and system info")
app.add_typer(models.app, name="models", help="List and manage models")
app.add_typer(queue.app, name="queue", help="Queue and execution management")
app.command(name="run")(run.run_workflow)


@app.command()
def version() -> None:
    """Show CLI version."""
    console.print(f"comfyui-cli v{__version__}")


@app.command()
def interrupt() -> None:
    """Interrupt current execution (shortcut)."""
    queue.interrupt()


@app.command()
def history(
    prompt_id: str = typer.Argument(None, help="Specific prompt ID"),
    max_items: int = typer.Option(10, "--max", "-n"),
) -> None:
    """Show execution history (shortcut)."""
    queue.history(prompt_id=prompt_id, max_items=max_items)


if __name__ == "__main__":
    app()
