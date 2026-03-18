"""Convert ComfyUI GUI workflow JSON to API prompt format and vice versa."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def gui_to_api(workflow: dict[str, Any]) -> dict[str, Any]:
    """Convert GUI-format workflow (with nodes/links) to API prompt format.

    The GUI format has:
        - nodes: list of node objects with id, type, widgets_values, inputs, outputs
        - links: list of [link_id, from_node, from_slot, to_node, to_slot, type]

    The API format is:
        - {node_id: {"class_type": ..., "inputs": {...}}}

    Args:
        workflow: GUI-format workflow dict (from .json export).

    Returns:
        API-format prompt dict.
    """
    nodes = workflow.get("nodes", [])
    links = workflow.get("links", [])

    # Build link lookup: link_id -> (from_node_id, from_slot_index)
    link_map: dict[int, tuple[int, int]] = {}
    for link in links:
        link_id, from_node, from_slot, _to_node, _to_slot, _type = link[:6]
        link_map[link_id] = (from_node, from_slot)

    # Build node lookup
    node_map: dict[int, dict] = {n["id"]: n for n in nodes}

    # Build object_info-like input order from node definitions
    prompt: dict[str, Any] = {}

    for node in nodes:
        node_id = str(node["id"])
        class_type = node.get("type", "")

        # Skip frontend-only nodes (reroute, notes, etc.)
        if class_type in ("Reroute", "Note", "PrimitiveNode"):
            continue

        inputs_dict: dict[str, Any] = {}

        # 1. Process linked inputs (from node.inputs)
        node_inputs = node.get("inputs", [])
        for inp in node_inputs:
            name = inp.get("name", "")
            link_id = inp.get("link")
            if link_id is not None and link_id in link_map:
                from_node_id, from_slot = link_map[link_id]
                inputs_dict[name] = [str(from_node_id), from_slot]

        # 2. Process widget values
        # Widget values fill in non-linked inputs in order
        widgets_values = node.get("widgets_values", [])
        if widgets_values:
            # We need to figure out which widget values go to which input names.
            # ComfyUI nodes define their inputs in order, and widgets_values
            # fills them in the order they appear (skipping linked inputs).
            #
            # Without object_info, we use a heuristic: assign widget_values
            # to inputs that are NOT linked, in order. For nodes with no
            # explicit input definitions for widgets, we store them indexed.

            # Get names of inputs that are linked
            linked_names = {inp["name"] for inp in node_inputs if inp.get("link") is not None}

            # Some nodes expose widget inputs in their inputs list
            widget_inputs = [inp for inp in node_inputs if inp.get("link") is None and inp.get("widget")]
            if widget_inputs:
                for i, winp in enumerate(widget_inputs):
                    if i < len(widgets_values):
                        inputs_dict[winp["name"]] = widgets_values[i]
            else:
                # Fallback: we'll need object_info to properly map these.
                # For now, store raw widget values - the enhance step will fix this.
                _assign_widget_values_heuristic(node, widgets_values, inputs_dict, linked_names)

        prompt[node_id] = {
            "class_type": class_type,
            "inputs": inputs_dict,
        }

    return prompt


def _assign_widget_values_heuristic(
    node: dict,
    widgets_values: list,
    inputs_dict: dict[str, Any],
    linked_names: set[str],
) -> None:
    """Best-effort assignment of widget values to input names.

    This works for common node types. For full accuracy, use
    enhance_with_object_info() after conversion.
    """
    class_type = node.get("type", "")

    # Known widget mappings for common nodes
    KNOWN_WIDGETS: dict[str, list[str]] = {
        "CLIPLoader": ["clip_name", "type", "device"],
        "UNETLoader": ["unet_name", "weight_dtype"],
        "VAELoader": ["vae_name"],
        "CheckpointLoaderSimple": ["ckpt_name"],
        "KSampler": ["seed", "control_after_generate", "steps", "cfg", "sampler_name", "scheduler", "denoise"],
        "KSamplerAdvanced": ["add_noise", "noise_seed", "control_after_generate", "steps", "cfg", "sampler_name", "scheduler", "start_at_step", "end_at_step", "return_with_leftover_noise"],
        "KSampler (Efficient)": ["seed", "control_after_generate", "steps", "cfg", "sampler_name", "scheduler", "denoise", "preview_method"],
        "KSampler Adv. (Efficient)": ["add_noise", "noise_seed", "control_after_generate", "steps", "cfg", "sampler_name", "scheduler", "start_at_step", "end_at_step", "return_with_leftover_noise", "preview_method"],
        "CLIPTextEncode": ["text"],
        "EmptyLatentImage": ["width", "height", "batch_size"],
        "SaveImage": ["filename_prefix"],
        "PreviewImage": [],
        "SetNode": ["name"],
        "GetNode": ["name"],
        "DF_Text_Box": ["text"],
        "Seed (rgthree)": ["seed"],
    }

    if class_type in KNOWN_WIDGETS:
        names = KNOWN_WIDGETS[class_type]
        for i, name in enumerate(names):
            if i < len(widgets_values) and name not in linked_names:
                inputs_dict[name] = widgets_values[i]
    else:
        # Unknown node type: store as _widgets_values for manual review
        inputs_dict["_widgets_values"] = widgets_values


def enhance_with_object_info(prompt: dict[str, Any], object_info: dict[str, Any]) -> dict[str, Any]:
    """Re-map widget values using server's object_info for accuracy.

    Args:
        prompt: API prompt dict (from gui_to_api).
        object_info: Full object_info response from ComfyUI server.

    Returns:
        Enhanced prompt with correct input names.
    """
    enhanced = {}

    for node_id, node_data in prompt.items():
        class_type = node_data["class_type"]
        inputs = dict(node_data["inputs"])

        if "_widgets_values" in inputs and class_type in object_info:
            raw_widgets = inputs.pop("_widgets_values")
            info = object_info[class_type]
            required = info.get("input", {}).get("required", {})
            optional = info.get("input", {}).get("optional", {})

            # Collect all input names in order (required first, then optional)
            all_input_names = list(required.keys()) + list(optional.keys())

            # Filter out names that are already set (linked inputs)
            linked_names = {k for k, v in inputs.items() if isinstance(v, list) and len(v) == 2}
            widget_names = [n for n in all_input_names if n not in linked_names]

            for i, name in enumerate(widget_names):
                if i < len(raw_widgets):
                    inputs[name] = raw_widgets[i]

        enhanced[node_id] = {
            "class_type": class_type,
            "inputs": inputs,
        }

    return enhanced


def load_workflow(path: str | Path) -> dict[str, Any]:
    """Load a workflow JSON file."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_workflow(workflow: dict[str, Any], path: str | Path) -> None:
    """Save a workflow JSON file."""
    Path(path).write_text(json.dumps(workflow, indent=2, ensure_ascii=False), encoding="utf-8")
