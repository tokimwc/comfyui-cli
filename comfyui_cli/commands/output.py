"""Output and image management commands."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ..client import ComfyUIClient
from ..config import Config

app = typer.Typer(help="Output file management.")
console = Console()


@app.callback(invoke_without_command=True)
def list_outputs(
    ctx: typer.Context,
    directory: str = typer.Option("output", "--dir", "-d", help="Directory type: output, input, or temp"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max files to show"),
) -> None:
    """List output files from ComfyUI."""
    if ctx.invoked_subcommand is not None:
        return

    config = Config.load()
    with ComfyUIClient(config) as client:
        if not client.is_alive():
            console.print(f"[red]ComfyUI is not running at {config.base_url}[/red]")
            raise typer.Exit(1)

        try:
            files = client.list_files(directory)
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)

        if not files:
            console.print(f"[dim]No files in '{directory}'.[/dim]")
            return

        # Sort by modification time (newest first) if available
        if isinstance(files, list) and files and isinstance(files[0], dict):
            files = sorted(files, key=lambda f: f.get("modified", 0), reverse=True)
            files = files[:limit]

            table = Table(title=f"Files: {directory}", border_style="blue")
            table.add_column("#", style="dim", width=4, justify="right")
            table.add_column("Filename", style="white")
            table.add_column("Size", style="cyan", justify="right")
            table.add_column("Subfolder", style="dim")

            for i, f in enumerate(files, 1):
                name = f.get("name", "unknown")
                size = f.get("size", 0)
                subfolder = f.get("subfolder", "")
                table.add_row(str(i), name, _fmt_bytes(size), subfolder)

            console.print(table)
        else:
            # Simple list
            for i, f in enumerate(files[:limit], 1):
                console.print(f"  {i}. {f}")

        console.print(f"\n[dim]Showing {min(limit, len(files))} of {len(files)} files[/dim]")


@app.command()
def open(
    filename: str = typer.Argument(..., help="Filename to open"),
    directory: str = typer.Option("output", "--dir", "-d", help="Directory type: output, input, or temp"),
) -> None:
    """Open an output file with the default application."""
    config = Config.load()
    with ComfyUIClient(config) as client:
        try:
            folder_paths = client.folder_paths()
        except Exception:
            folder_paths = {}

        # Try to find the file path
        dir_paths = folder_paths.get(directory, [[]])
        if isinstance(dir_paths, list) and dir_paths:
            base_dir = dir_paths[0] if isinstance(dir_paths[0], str) else dir_paths[0][0] if dir_paths[0] else ""
        else:
            base_dir = ""

        if base_dir:
            full_path = Path(base_dir) / filename
        else:
            full_path = Path(filename)

        if not full_path.exists():
            console.print(f"[red]File not found: {full_path}[/red]")
            raise typer.Exit(1)

        console.print(f"Opening: {full_path}")
        if sys.platform == "win32":
            os.startfile(str(full_path))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(full_path)])
        else:
            subprocess.run(["xdg-open", str(full_path)])


@app.command()
def save(
    filename: str = typer.Argument(..., help="Filename to download"),
    output_path: str = typer.Argument(None, help="Local path to save (default: current directory)"),
    directory: str = typer.Option("output", "--dir", "-d", help="Source directory: output, input, or temp"),
    subfolder: str = typer.Option("", "--subfolder", "-s", help="Subfolder within directory"),
) -> None:
    """Download an output file from ComfyUI to local disk."""
    config = Config.load()
    with ComfyUIClient(config) as client:
        try:
            data = client.view_image(filename, subfolder=subfolder, image_type=directory)
        except Exception as e:
            console.print(f"[red]Error downloading: {e}[/red]")
            raise typer.Exit(1)

        save_path = Path(output_path) if output_path else Path(filename)
        save_path.write_bytes(data)
        console.print(f"[green]Saved:[/green] {save_path} ({_fmt_bytes(len(data))})")


@app.command()
def upload(
    file_path: str = typer.Argument(..., help="Path to image file to upload"),
    subfolder: str = typer.Option("", "--subfolder", "-s", help="Subfolder in input directory"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite if exists"),
) -> None:
    """Upload an image to ComfyUI input directory."""
    path = Path(file_path)
    if not path.exists():
        console.print(f"[red]File not found: {file_path}[/red]")
        raise typer.Exit(1)

    config = Config.load()
    with ComfyUIClient(config) as client:
        try:
            result = client.upload_image(path, subfolder=subfolder, overwrite=overwrite)
            name = result.get("name", path.name)
            console.print(f"[green]Uploaded:[/green] {name}")
            if result.get("subfolder"):
                console.print(f"[dim]Subfolder: {result['subfolder']}[/dim]")
        except Exception as e:
            console.print(f"[red]Upload failed: {e}[/red]")
            raise typer.Exit(1)


def _fmt_bytes(b: int) -> str:
    """Format bytes as human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"
