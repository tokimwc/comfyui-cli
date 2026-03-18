"""Workflow execution command."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from ..client import ComfyUIClient
from ..config import Config
from ..workflow_converter import gui_to_api, enhance_with_object_info, load_workflow
from ..ws_client import run_monitor

console = Console()


def run_workflow(
    workflow_path: str = typer.Argument(..., help="Path to workflow JSON file"),
    seed: int = typer.Option(None, "--seed", "-s", help="Override seed value"),
    prompt_text: str = typer.Option(None, "--prompt", "-P", help="Override positive prompt text"),
    negative: str = typer.Option(None, "--negative", "-N", help="Override negative prompt text"),
    batch: int = typer.Option(1, "--batch", "-b", help="Number of times to run"),
    watch: bool = typer.Option(True, "--watch/--no-watch", "-w", help="Watch progress via WebSocket"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Convert and show API prompt without executing"),
) -> None:
    """Execute a ComfyUI workflow from the terminal.

    Accepts both GUI-format and API-format workflow JSON files.
    GUI-format files (with nodes/links) are automatically converted to API format.
    """
    path = Path(workflow_path)
    if not path.exists():
        console.print(f"[red]File not found: {workflow_path}[/red]")
        raise typer.Exit(1)

    # Load workflow
    workflow = load_workflow(path)

    # Detect format: GUI format has "nodes" key, API format has node IDs as keys
    is_gui_format = "nodes" in workflow and "links" in workflow

    if is_gui_format:
        console.print("[dim]Detected GUI format, converting to API format...[/dim]")
        api_prompt = gui_to_api(workflow)

        # Enhance with object_info from server
        config = Config.load()
        with ComfyUIClient(config) as client:
            if not client.is_alive():
                console.print(f"[red]ComfyUI is not running at {config.base_url}[/red]")
                raise typer.Exit(1)
            try:
                obj_info = client.object_info()
                api_prompt = enhance_with_object_info(api_prompt, obj_info)
            except Exception as e:
                console.print(f"[yellow]Warning: Could not enhance with object_info: {e}[/yellow]")
    else:
        # Already API format
        api_prompt = workflow

    # Apply overrides
    if seed is not None:
        _override_seed(api_prompt, seed)
    if prompt_text is not None:
        _override_prompt(api_prompt, prompt_text, positive=True)
    if negative is not None:
        _override_prompt(api_prompt, negative, positive=False)

    if dry_run:
        console.print("[bold]API Prompt (dry run):[/bold]")
        console.print_json(data=api_prompt)
        return

    # Execute
    config = Config.load()
    with ComfyUIClient(config) as client:
        if not client.is_alive():
            console.print(f"[red]ComfyUI is not running at {config.base_url}[/red]")
            raise typer.Exit(1)

        for i in range(batch):
            if batch > 1:
                console.print(f"\n[bold cyan]── Batch {i + 1}/{batch} ──[/bold cyan]")
                if seed is not None:
                    _override_seed(api_prompt, seed + i)

            try:
                result = client.queue_prompt(api_prompt)
                prompt_id = result.get("prompt_id", "unknown")
                console.print(f"[green]Queued:[/green] {prompt_id}")
            except Exception as e:
                error_detail = str(e)
                console.print(f"[red]Failed to queue: {error_detail}[/red]")

                # Try to extract node errors from response
                if hasattr(e, "response"):
                    try:
                        err_body = e.response.json()
                        node_errors = err_body.get("node_errors", {})
                        for nid, nerr in node_errors.items():
                            console.print(f"  [red]Node {nid} ({nerr.get('class_type', '?')}): {nerr.get('errors', [])}[/red]")
                    except Exception:
                        pass
                raise typer.Exit(1)

            if watch:
                _watch_execution(config, client.client_id, prompt_id)


def _watch_execution(config: Config, client_id: str, prompt_id: str) -> None:
    """Monitor execution progress via WebSocket."""
    current_node = ""
    step_progress: dict[str, tuple[int, int]] = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Waiting...", total=None)

        def on_progress(data: dict[str, Any]) -> None:
            nonlocal current_node
            msg_type = data.get("type", "")
            msg_data = data.get("data", {})

            if msg_type == "execution_cached":
                cached = msg_data.get("nodes", [])
                if cached:
                    progress.update(task, description=f"[dim]Cached: {len(cached)} nodes[/dim]")

            elif msg_type == "executing":
                node_id = msg_data.get("node")
                if node_id:
                    current_node = node_id
                    progress.update(task, description=f"Node: {node_id}")

            elif msg_type == "progress":
                value = msg_data.get("value", 0)
                max_val = msg_data.get("max", 0)
                if max_val > 0:
                    progress.update(task, completed=value, total=max_val, description=f"Node: {current_node}")

        result = run_monitor(config, client_id, prompt_id, on_progress)

    # Show result
    status = result.get("status", "unknown")
    if status == "completed":
        console.print(f"[bold green]Completed![/bold green] prompt_id={prompt_id}")
    elif status == "error":
        console.print(f"[bold red]Error![/bold red] Node {result.get('node_id')}: {result.get('message')}")
    elif status == "interrupted":
        console.print(f"[yellow]Interrupted.[/yellow]")
    else:
        console.print(f"[yellow]Status: {status}[/yellow]")


def _override_seed(prompt: dict[str, Any], seed: int) -> None:
    """Override seed values in the prompt."""
    for node_id, node_data in prompt.items():
        inputs = node_data.get("inputs", {})
        if "seed" in inputs:
            inputs["seed"] = seed
        if "noise_seed" in inputs:
            inputs["noise_seed"] = seed


def _override_prompt(prompt: dict[str, Any], text: str, positive: bool = True) -> None:
    """Override prompt text in CLIPTextEncode nodes.

    Uses heuristic: positive prompts have 'positive' or 'pos' in node title/connections,
    negative have 'negative' or 'neg'.
    """
    for node_id, node_data in prompt.items():
        if node_data.get("class_type") != "CLIPTextEncode":
            continue
        inputs = node_data.get("inputs", {})
        if "text" not in inputs:
            continue

        # Try to determine if positive or negative by existing text content
        current_text = str(inputs.get("text", ""))
        is_negative = any(kw in current_text.lower() for kw in ["worst quality", "low quality", "bad", "ugly", "blurry"])

        if positive and not is_negative:
            inputs["text"] = text
        elif not positive and is_negative:
            inputs["text"] = text
