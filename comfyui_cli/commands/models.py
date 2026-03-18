"""Model management commands."""

from __future__ import annotations

from pathlib import PurePosixPath

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from ..client import ComfyUIClient
from ..config import Config

app = typer.Typer(help="Model management.")
console = Console()


@app.callback(invoke_without_command=True)
def list_models(
    ctx: typer.Context,
    folder: str = typer.Argument(None, help="Model folder type (e.g., checkpoints, clip, vae, diffusion_models)"),
    tree: bool = typer.Option(False, "--tree", "-t", help="Show as tree view"),
) -> None:
    """List available models. Without arguments, shows all folder types."""
    if ctx.invoked_subcommand is not None:
        return

    config = Config.load()
    with ComfyUIClient(config) as client:
        if folder:
            _show_folder_models(client, folder, tree)
        else:
            _show_all_folders(client)


def _show_all_folders(client: ComfyUIClient) -> None:
    """Show summary of all model folders."""
    folders = client.model_folders()

    table = Table(title="Model Folders", border_style="blue")
    table.add_column("Folder", style="cyan")
    table.add_column("Count", style="white", justify="right")

    for f in sorted(folders):
        try:
            models = client.models(f)
            table.add_row(f, str(len(models)))
        except Exception:
            table.add_row(f, "[dim]error[/dim]")

    console.print(table)
    console.print(f"\n[dim]Use [cyan]comfyui models <folder>[/cyan] to see models in a folder.[/dim]")


def _show_folder_models(client: ComfyUIClient, folder: str, as_tree: bool) -> None:
    """Show models in a specific folder."""
    try:
        models = client.models(folder)
    except Exception as e:
        console.print(f"[red]Error listing {folder}: {e}[/red]")
        raise typer.Exit(1)

    if not models:
        console.print(f"[yellow]No models found in '{folder}'.[/yellow]")
        return

    if as_tree:
        tree = Tree(f"[bold cyan]{folder}[/bold cyan] ({len(models)} models)")
        # Group by subdirectory
        dirs: dict[str, list[str]] = {}
        for m in sorted(models):
            parts = PurePosixPath(m).parts
            if len(parts) > 1:
                subdir = str(PurePosixPath(*parts[:-1]))
                dirs.setdefault(subdir, []).append(parts[-1])
            else:
                dirs.setdefault(".", []).append(m)

        for d in sorted(dirs.keys()):
            if d == ".":
                for f in dirs[d]:
                    tree.add(f"[white]{f}[/white]")
            else:
                branch = tree.add(f"[blue]{d}/[/blue]")
                for f in dirs[d]:
                    branch.add(f"[white]{f}[/white]")

        console.print(tree)
    else:
        table = Table(title=f"Models: {folder}", border_style="blue")
        table.add_column("#", style="dim", width=4, justify="right")
        table.add_column("Model", style="white")

        for i, m in enumerate(sorted(models), 1):
            table.add_row(str(i), m)

        console.print(table)

    console.print(f"\n[dim]Total: {len(models)} models[/dim]")
