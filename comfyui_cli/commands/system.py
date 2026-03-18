"""System information commands."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from ..client import ComfyUIClient
from ..config import Config

app = typer.Typer(help="System information and management.")
console = Console()


@app.callback(invoke_without_command=True)
def status(
    ctx: typer.Context,
    host: str = typer.Option(None, "--host", "-h", help="ComfyUI host"),
    port: int = typer.Option(None, "--port", "-p", help="ComfyUI port"),
) -> None:
    """Show ComfyUI server status and system info."""
    if ctx.invoked_subcommand is not None:
        return

    config = Config.load()
    if host:
        config.host = host
    if port:
        config.port = port

    with ComfyUIClient(config) as client:
        if not client.is_alive():
            console.print(f"[red]ComfyUI is not running at {config.base_url}[/red]")
            raise typer.Exit(1)

        stats = client.system_stats()
        sys_info = stats["system"]
        devices = stats.get("devices", [])

        # System info table
        table = Table(title="ComfyUI Server Status", show_header=False, border_style="blue")
        table.add_column("Key", style="cyan", width=20)
        table.add_column("Value", style="white")

        table.add_row("Status", "[green]Running[/green]")
        table.add_row("URL", config.base_url)
        table.add_row("ComfyUI Version", sys_info.get("comfyui_version", "unknown"))
        table.add_row("Python", sys_info.get("python_version", "unknown").split("(")[0].strip())
        table.add_row("PyTorch", sys_info.get("pytorch_version", "unknown"))

        ram_total = sys_info.get("ram_total", 0)
        ram_free = sys_info.get("ram_free", 0)
        ram_used = ram_total - ram_free
        if ram_total > 0:
            pct = ram_used / ram_total * 100
            table.add_row(
                "RAM",
                f"{_fmt_bytes(ram_used)} / {_fmt_bytes(ram_total)} ({pct:.0f}% used)",
            )

        console.print(table)

        # GPU table
        if devices:
            gpu_table = Table(title="GPU Devices", border_style="green")
            gpu_table.add_column("Device", style="cyan")
            gpu_table.add_column("VRAM Total", style="white", justify="right")
            gpu_table.add_column("VRAM Free", style="white", justify="right")
            gpu_table.add_column("Usage", style="white", justify="right")

            for dev in devices:
                vram_total = dev.get("vram_total", 0)
                vram_free = dev.get("vram_free", 0)
                vram_used = vram_total - vram_free
                pct = (vram_used / vram_total * 100) if vram_total > 0 else 0
                name = dev.get("name", "unknown").replace(" : native", "")
                gpu_table.add_row(
                    name,
                    _fmt_bytes(vram_total),
                    _fmt_bytes(vram_free),
                    f"{pct:.1f}%",
                )

            console.print(gpu_table)

        # Queue info
        queue = client.get_queue()
        running = len(queue.get("queue_running", []))
        pending = len(queue.get("queue_pending", []))
        console.print(f"\n[dim]Queue:[/dim] {running} running, {pending} pending")


@app.command()
def free(
    unload: bool = typer.Option(True, "--unload/--no-unload", help="Unload models from VRAM"),
) -> None:
    """Free GPU memory and optionally unload models."""
    config = Config.load()
    with ComfyUIClient(config) as client:
        client.free_memory(unload_models=unload, free_memory=True)
        console.print("[green]Memory freed.[/green]")
        if unload:
            console.print("[dim]Models unloaded from VRAM.[/dim]")


def _fmt_bytes(b: int) -> str:
    """Format bytes as human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"
