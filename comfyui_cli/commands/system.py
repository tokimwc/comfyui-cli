"""System information commands."""

from __future__ import annotations

import subprocess

import typer
from rich.bar import Bar
from rich.console import Console
from rich.table import Table
from rich.text import Text

from ..client import ComfyUIClient
from ..config import Config

app = typer.Typer(help="System information and management.")
console = Console()


def _get_config(host: str | None = None, port: int | None = None) -> Config:
    """Build Config with optional overrides."""
    config = Config.load()
    if host:
        config.host = host
    if port:
        config.port = port
    return config


@app.callback(invoke_without_command=True)
def status(
    ctx: typer.Context,
    host: str = typer.Option(None, "--host", "-h", help="ComfyUI host"),
    port: int = typer.Option(None, "--port", "-p", help="ComfyUI port"),
) -> None:
    """Show ComfyUI server status and system info."""
    if ctx.invoked_subcommand is not None:
        return

    config = _get_config(host, port)

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
def gpu() -> None:
    """Show detailed GPU utilization (nvidia-smi + ComfyUI VRAM)."""
    config = _get_config()

    # --- nvidia-smi data ---
    smi = _query_nvidia_smi()

    if not smi:
        console.print("[red]nvidia-smi not found or no NVIDIA GPU detected.[/red]")
        raise typer.Exit(1)

    table = Table(title="GPU Utilization", border_style="green")
    table.add_column("", style="dim", width=12)
    for i, g in enumerate(smi):
        table.add_column(f"GPU {i}: {g['name']}", style="white", min_width=30)

    # GPU Utilization row
    vals = []
    for g in smi:
        pct = g["gpu_util"]
        bar = _usage_bar(pct, width=20)
        vals.append(Text.assemble(bar, f" {pct}%"))
    table.add_row("GPU Util", *vals)

    # VRAM row (nvidia-smi)
    vals = []
    for g in smi:
        used, total = g["mem_used_mb"], g["mem_total_mb"]
        pct = used / total * 100 if total > 0 else 0
        bar = _usage_bar(pct, width=20)
        vals.append(Text.assemble(bar, f" {used} / {total} MB ({pct:.0f}%)"))
    table.add_row("VRAM", *vals)

    # Temperature row
    vals = []
    for g in smi:
        temp = g["temperature"]
        color = "green" if temp < 70 else ("yellow" if temp < 85 else "red")
        vals.append(Text(f"{temp} C", style=color))
    table.add_row("Temperature", *vals)

    # Power row
    vals = []
    for g in smi:
        pwr = g["power_draw"]
        plimit = g["power_limit"]
        pct = pwr / plimit * 100 if plimit > 0 else 0
        vals.append(Text(f"{pwr:.0f} / {plimit:.0f} W ({pct:.0f}%)"))
    table.add_row("Power", *vals)

    # Fan row
    vals = []
    for g in smi:
        fan = g["fan_speed"]
        vals.append(Text(f"{fan}%" if fan >= 0 else "N/A"))
    table.add_row("Fan", *vals)

    console.print(table)

    # --- ComfyUI torch VRAM ---
    try:
        with ComfyUIClient(config) as client:
            if client.is_alive():
                stats = client.system_stats()
                devices = stats.get("devices", [])
                if devices:
                    torch_table = Table(title="ComfyUI Torch VRAM", border_style="blue")
                    torch_table.add_column("Device", style="cyan")
                    torch_table.add_column("Torch Alloc", justify="right")
                    torch_table.add_column("Torch Free", justify="right")
                    torch_table.add_column("Total VRAM", justify="right")
                    torch_table.add_column("Torch Usage", justify="right")

                    for dev in devices:
                        name = dev.get("name", "unknown").replace(" : native", "")
                        torch_total = dev.get("torch_vram_total", 0)
                        torch_free = dev.get("torch_vram_free", 0)
                        vram_total = dev.get("vram_total", 0)
                        torch_used = torch_total - torch_free

                        if torch_total > 0:
                            pct = torch_used / vram_total * 100 if vram_total > 0 else 0
                            torch_table.add_row(
                                name,
                                _fmt_bytes(torch_used),
                                _fmt_bytes(torch_free),
                                _fmt_bytes(vram_total),
                                f"{pct:.1f}%",
                            )
                        else:
                            torch_table.add_row(
                                name,
                                "[dim]No models loaded[/dim]",
                                "-",
                                _fmt_bytes(vram_total),
                                "0.0%",
                            )

                    console.print(torch_table)
            else:
                console.print("\n[dim]ComfyUI not running - torch VRAM info unavailable[/dim]")
    except Exception:
        console.print("\n[dim]ComfyUI not running - torch VRAM info unavailable[/dim]")


@app.command()
def watch(
    interval: int = typer.Option(2, "--interval", "-i", help="Refresh interval in seconds"),
) -> None:
    """Live-monitor GPU utilization (auto-refresh)."""
    import time

    config = _get_config()

    try:
        while True:
            console.clear()
            smi = _query_nvidia_smi()
            if not smi:
                console.print("[red]nvidia-smi not available[/red]")
                break

            for i, g in enumerate(smi):
                gpu_pct = g["gpu_util"]
                mem_used, mem_total = g["mem_used_mb"], g["mem_total_mb"]
                mem_pct = mem_used / mem_total * 100 if mem_total > 0 else 0
                temp = g["temperature"]
                pwr = g["power_draw"]

                temp_color = "green" if temp < 70 else ("yellow" if temp < 85 else "red")

                console.print(
                    Text.assemble(
                        (f"GPU {i} ", "bold cyan"),
                        (g["name"], "white"),
                        ("  |  ", "dim"),
                        ("GPU ", "dim"),
                        _usage_bar(gpu_pct, width=15),
                        (f" {gpu_pct:3d}%", "white"),
                        ("  |  ", "dim"),
                        ("VRAM ", "dim"),
                        _usage_bar(mem_pct, width=15),
                        (f" {mem_used}/{mem_total}MB", "white"),
                        ("  |  ", "dim"),
                        (f"{temp}C", temp_color),
                        ("  ", ""),
                        (f"{pwr:.0f}W", "white"),
                    )
                )

            # ComfyUI queue
            try:
                with ComfyUIClient(config) as client:
                    if client.is_alive():
                        q = client.get_queue()
                        running = len(q.get("queue_running", []))
                        pending = len(q.get("queue_pending", []))
                        if running or pending:
                            console.print(
                                f"\n[bold]Queue:[/bold] [green]{running} running[/green], {pending} pending"
                            )
            except Exception:
                pass

            console.print(f"\n[dim]Refreshing every {interval}s. Ctrl+C to stop.[/dim]")
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")


@app.command()
def free(
    unload: bool = typer.Option(True, "--unload/--no-unload", help="Unload models from VRAM"),
) -> None:
    """Free GPU memory and optionally unload models."""
    config = _get_config()
    with ComfyUIClient(config) as client:
        client.free_memory(unload_models=unload, free_memory=True)
        console.print("[green]Memory freed.[/green]")
        if unload:
            console.print("[dim]Models unloaded from VRAM.[/dim]")


# ── Helpers ──────────────────────────────────────────────


def _query_nvidia_smi() -> list[dict] | None:
    """Query nvidia-smi for GPU stats. Returns None if unavailable."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total,"
                "temperature.gpu,power.draw,power.limit,fan.speed",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None

        gpus = []
        for line in result.stdout.strip().split("\n"):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 8:
                continue
            gpus.append(
                {
                    "name": parts[0],
                    "gpu_util": int(parts[1]),
                    "mem_used_mb": int(parts[2]),
                    "mem_total_mb": int(parts[3]),
                    "temperature": int(parts[4]),
                    "power_draw": float(parts[5]),
                    "power_limit": float(parts[6]),
                    "fan_speed": int(parts[7]) if parts[7] != "[N/A]" else -1,
                }
            )
        return gpus if gpus else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _usage_bar(pct: float, width: int = 20) -> Text:
    """Create a colored usage bar text."""
    filled = int(pct / 100 * width)
    empty = width - filled

    if pct < 50:
        color = "green"
    elif pct < 80:
        color = "yellow"
    else:
        color = "red"

    return Text.assemble(
        ("[", "dim"),
        ("=" * filled, color),
        (" " * empty, ""),
        ("]", "dim"),
    )


def _fmt_bytes(b: int) -> str:
    """Format bytes as human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"
