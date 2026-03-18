"""Queue and execution management commands."""

from __future__ import annotations

from datetime import datetime

import typer
from rich.console import Console
from rich.table import Table

from ..client import ComfyUIClient
from ..config import Config

app = typer.Typer(help="Queue and execution management.")
console = Console()


@app.callback(invoke_without_command=True)
def show_queue(ctx: typer.Context) -> None:
    """Show current queue status."""
    if ctx.invoked_subcommand is not None:
        return

    config = Config.load()
    with ComfyUIClient(config) as client:
        queue = client.get_queue()
        running = queue.get("queue_running", [])
        pending = queue.get("queue_pending", [])

        if not running and not pending:
            console.print("[dim]Queue is empty.[/dim]")
            return

        if running:
            table = Table(title="Running", border_style="green")
            table.add_column("Prompt ID", style="cyan")
            table.add_column("Queued At", style="white")
            for item in running:
                prompt_id = item[1] if len(item) > 1 else "unknown"
                table.add_row(str(prompt_id), "now")
            console.print(table)

        if pending:
            table = Table(title="Pending", border_style="yellow")
            table.add_column("#", style="dim", width=4, justify="right")
            table.add_column("Prompt ID", style="cyan")
            for i, item in enumerate(pending, 1):
                prompt_id = item[1] if len(item) > 1 else "unknown"
                table.add_row(str(i), str(prompt_id))
            console.print(table)

        console.print(f"\n[dim]{len(running)} running, {len(pending)} pending[/dim]")


@app.command()
def clear() -> None:
    """Clear all pending items from the queue."""
    config = Config.load()
    with ComfyUIClient(config) as client:
        client.clear_queue()
        console.print("[green]Queue cleared.[/green]")


@app.command()
def interrupt() -> None:
    """Interrupt the currently running generation."""
    config = Config.load()
    with ComfyUIClient(config) as client:
        client.interrupt()
        console.print("[yellow]Interrupted current execution.[/yellow]")


@app.command()
def history(
    prompt_id: str = typer.Argument(None, help="Specific prompt ID to inspect"),
    max_items: int = typer.Option(10, "--max", "-n", help="Max history items to show"),
) -> None:
    """Show execution history."""
    config = Config.load()
    with ComfyUIClient(config) as client:
        hist = client.history(prompt_id=prompt_id, max_items=max_items)

        if not hist:
            console.print("[dim]No history found.[/dim]")
            return

        if prompt_id:
            # Detailed view for single prompt
            data = hist.get(prompt_id, hist)
            console.print_json(data=data)
        else:
            # Summary table
            table = Table(title="Execution History", border_style="blue")
            table.add_column("Prompt ID", style="cyan", max_width=20)
            table.add_column("Status", style="white")
            table.add_column("Nodes", style="white", justify="right")
            table.add_column("Outputs", style="white", justify="right")

            for pid, entry in list(hist.items())[:max_items]:
                status_data = entry.get("status", {})
                status = status_data.get("status_str", "unknown")
                status_style = {
                    "success": "[green]success[/green]",
                    "error": "[red]error[/red]",
                }.get(status, f"[yellow]{status}[/yellow]")

                outputs = entry.get("outputs", {})
                node_count = len(entry.get("prompt", [None, None, {}])[2]) if entry.get("prompt") else 0
                output_count = sum(1 for o in outputs.values() if o)

                table.add_row(
                    pid[:18] + ".." if len(pid) > 20 else pid,
                    status_style,
                    str(node_count),
                    str(output_count),
                )

            console.print(table)
