"""Workflow format conversion commands."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from ..client import ComfyUIClient
from ..config import Config
from ..workflow_converter import gui_to_api, enhance_with_object_info, load_workflow, save_workflow

console = Console()


def convert_workflow(
    input_path: str = typer.Argument(..., help="Input workflow JSON file"),
    output_path: str = typer.Argument(None, help="Output file path (default: <input>_api.json)"),
    enhance: bool = typer.Option(True, "--enhance/--no-enhance", help="Enhance with server object_info"),
) -> None:
    """Convert GUI-format workflow to API-format.

    Resolves SetNode/GetNode, removes frontend-only nodes, and maps
    widget values to correct input names using the ComfyUI server.
    """
    src = Path(input_path)
    if not src.exists():
        console.print(f"[red]File not found: {input_path}[/red]")
        raise typer.Exit(1)

    workflow = load_workflow(src)

    # Check format
    if "nodes" not in workflow or "links" not in workflow:
        console.print("[yellow]File appears to already be in API format.[/yellow]")
        raise typer.Exit(0)

    console.print(f"[dim]Converting: {src.name}[/dim]")

    # Convert
    api_prompt = gui_to_api(workflow)
    node_count_before = len(workflow.get("nodes", []))
    node_count_after = len(api_prompt)
    console.print(f"[dim]  Nodes: {node_count_before} (GUI) -> {node_count_after} (API)[/dim]")

    # Enhance with object_info
    if enhance:
        config = Config.load()
        with ComfyUIClient(config) as client:
            if client.is_alive():
                try:
                    obj_info = client.object_info()
                    api_prompt = enhance_with_object_info(api_prompt, obj_info)
                    console.print("[dim]  Enhanced with server object_info[/dim]")
                except Exception as e:
                    console.print(f"[yellow]  Warning: enhance failed: {e}[/yellow]")
            else:
                console.print("[yellow]  Server not running, skipping enhance[/yellow]")

    # Determine output path
    if output_path:
        dst = Path(output_path)
    else:
        dst = src.with_name(src.stem + "_api.json")

    save_workflow(api_prompt, dst)
    console.print(f"[green]Saved:[/green] {dst}")

    # Show summary
    types = {}
    for nd in api_prompt.values():
        ct = nd.get("class_type", "unknown")
        types[ct] = types.get(ct, 0) + 1
    console.print("\n[bold]Node types:[/bold]")
    for ct, count in sorted(types.items()):
        console.print(f"  {ct}: {count}")
