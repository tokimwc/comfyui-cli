"""Prompt template management commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table
from rich.syntax import Syntax

from ..config import CONFIG_DIR

app = typer.Typer(help="Prompt template management.")
console = Console()

TEMPLATE_DIR = CONFIG_DIR / "templates"


def _ensure_template_dir() -> Path:
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    return TEMPLATE_DIR


def _load_template(name: str) -> dict[str, Any]:
    path = TEMPLATE_DIR / f"{name}.json"
    if not path.exists():
        console.print(f"[red]Template not found: {name}[/red]")
        raise typer.Exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


@app.callback(invoke_without_command=True)
def list_templates(ctx: typer.Context) -> None:
    """List saved prompt templates."""
    if ctx.invoked_subcommand is not None:
        return

    _ensure_template_dir()
    templates = sorted(TEMPLATE_DIR.glob("*.json"))

    if not templates:
        console.print("[dim]No templates saved yet.[/dim]")
        console.print("[dim]Use [cyan]comfyui template save <name> --positive '...' --negative '...'[/cyan] to create one.[/dim]")
        return

    table = Table(title="Prompt Templates", border_style="blue")
    table.add_column("Name", style="cyan")
    table.add_column("Positive", style="white", max_width=50)
    table.add_column("Negative", style="dim", max_width=30)
    table.add_column("Params", style="yellow")

    for t in templates:
        data = json.loads(t.read_text(encoding="utf-8"))
        pos = data.get("positive", "")[:48]
        neg = data.get("negative", "")[:28]
        params = []
        if "seed" in data:
            params.append(f"seed={data['seed']}")
        if "steps" in data:
            params.append(f"steps={data['steps']}")
        if "cfg" in data:
            params.append(f"cfg={data['cfg']}")
        if "width" in data and "height" in data:
            params.append(f"{data['width']}x{data['height']}")

        table.add_row(
            t.stem,
            pos + ("..." if len(data.get("positive", "")) > 48 else ""),
            neg + ("..." if len(data.get("negative", "")) > 28 else ""),
            ", ".join(params) if params else "-",
        )

    console.print(table)


@app.command()
def save(
    name: str = typer.Argument(..., help="Template name"),
    positive: str = typer.Option(..., "--positive", "-p", help="Positive prompt text"),
    negative: str = typer.Option("worst quality, low quality, blurry, jpeg artifacts", "--negative", "-n", help="Negative prompt text"),
    seed: int = typer.Option(None, "--seed", "-s", help="Seed value"),
    steps: int = typer.Option(None, "--steps", help="Number of steps"),
    cfg: float = typer.Option(None, "--cfg", help="CFG scale"),
    width: int = typer.Option(None, "--width", "-W", help="Image width"),
    height: int = typer.Option(None, "--height", "-H", help="Image height"),
    sampler: str = typer.Option(None, "--sampler", help="Sampler name"),
    scheduler: str = typer.Option(None, "--scheduler", help="Scheduler name"),
) -> None:
    """Save a prompt template."""
    _ensure_template_dir()

    data: dict[str, Any] = {
        "positive": positive,
        "negative": negative,
    }
    if seed is not None:
        data["seed"] = seed
    if steps is not None:
        data["steps"] = steps
    if cfg is not None:
        data["cfg"] = cfg
    if width is not None:
        data["width"] = width
    if height is not None:
        data["height"] = height
    if sampler is not None:
        data["sampler_name"] = sampler
    if scheduler is not None:
        data["scheduler"] = scheduler

    path = TEMPLATE_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]Saved template:[/green] {name}")


@app.command()
def show(
    name: str = typer.Argument(..., help="Template name"),
) -> None:
    """Show a template's contents."""
    data = _load_template(name)
    console.print_json(data=data)


@app.command()
def delete(
    name: str = typer.Argument(..., help="Template name to delete"),
) -> None:
    """Delete a template."""
    path = TEMPLATE_DIR / f"{name}.json"
    if not path.exists():
        console.print(f"[red]Template not found: {name}[/red]")
        raise typer.Exit(1)
    path.unlink()
    console.print(f"[green]Deleted:[/green] {name}")


@app.command()
def apply(
    name: str = typer.Argument(..., help="Template name"),
    workflow_path: str = typer.Argument(..., help="Workflow JSON to apply template to"),
    output_path: str = typer.Argument(None, help="Output path (default: overwrite input)"),
) -> None:
    """Apply a template's parameters to a workflow (API format).

    Overrides prompt text, seed, steps, cfg, resolution, sampler, and scheduler
    in the workflow based on template values.
    """
    data = _load_template(name)
    wf_path = Path(workflow_path)

    if not wf_path.exists():
        console.print(f"[red]Workflow not found: {workflow_path}[/red]")
        raise typer.Exit(1)

    workflow = json.loads(wf_path.read_text(encoding="utf-8"))

    changes = 0

    for node_id, node_data in workflow.items():
        if not isinstance(node_data, dict):
            continue
        ct = node_data.get("class_type", "")
        inputs = node_data.get("inputs", {})

        # Apply prompt text
        if ct == "CLIPTextEncode" and "text" in inputs:
            current = str(inputs.get("text", ""))
            is_neg = any(kw in current.lower() for kw in ["worst quality", "low quality", "bad", "ugly", "blurry"])
            if not is_neg and "positive" in data:
                inputs["text"] = data["positive"]
                changes += 1
            elif is_neg and "negative" in data:
                inputs["text"] = data["negative"]
                changes += 1

        elif ct == "DF_Text_Box" and "Text" in inputs:
            current = str(inputs.get("Text", ""))
            is_neg = any(kw in current.lower() for kw in ["worst quality", "low quality", "bad", "ugly", "blurry"])
            if not is_neg and "positive" in data:
                inputs["Text"] = data["positive"]
                changes += 1
            elif is_neg and "negative" in data:
                inputs["Text"] = data["negative"]
                changes += 1

        # Apply sampler settings
        if "KSampler" in ct:
            for key in ("seed", "noise_seed", "steps", "cfg", "sampler_name", "scheduler"):
                if key in data and key in inputs:
                    inputs[key] = data[key]
                    changes += 1
                elif key == "seed" and "seed" in data and "noise_seed" in inputs:
                    inputs["noise_seed"] = data["seed"]
                    changes += 1

        # Apply resolution
        if ct == "EmptyLatentImage":
            if "width" in data and "width" in inputs:
                inputs["width"] = data["width"]
                changes += 1
            if "height" in data and "height" in inputs:
                inputs["height"] = data["height"]
                changes += 1

    # Save
    out = Path(output_path) if output_path else wf_path
    out.write_text(json.dumps(workflow, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]Applied template '{name}':[/green] {changes} parameters updated")
    console.print(f"[dim]Saved to: {out}[/dim]")
