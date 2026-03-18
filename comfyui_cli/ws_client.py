"""WebSocket client for real-time progress monitoring."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

import websockets

from .config import Config


async def monitor_progress(
    config: Config,
    client_id: str,
    prompt_id: str,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    on_preview: Callable[[bytes], None] | None = None,
) -> dict[str, Any]:
    """Monitor execution progress via WebSocket.

    Connects to ComfyUI's WebSocket and listens for execution events
    until the specified prompt_id completes or fails.

    Args:
        config: CLI configuration.
        client_id: Client ID matching the one used in queue_prompt.
        prompt_id: The prompt ID to monitor.
        on_progress: Callback for progress updates.
        on_preview: Callback for preview image data.

    Returns:
        Final execution result or error info.
    """
    uri = f"{config.ws_url}?clientId={client_id}"
    result: dict[str, Any] = {"status": "unknown"}

    async with websockets.connect(uri) as ws:
        while True:
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=300)
            except asyncio.TimeoutError:
                result = {"status": "timeout", "message": "No response for 5 minutes"}
                break

            if isinstance(message, bytes):
                # Binary message = preview image
                if on_preview:
                    # First 8 bytes are metadata (type + format), rest is image
                    on_preview(message[8:] if len(message) > 8 else message)
                continue

            data = json.loads(message)
            msg_type = data.get("type", "")
            msg_data = data.get("data", {})

            if on_progress:
                on_progress(data)

            if msg_type == "executing":
                # node is None when execution is complete
                if msg_data.get("prompt_id") == prompt_id and msg_data.get("node") is None:
                    result = {"status": "completed", "prompt_id": prompt_id}
                    break

            elif msg_type == "execution_error":
                if msg_data.get("prompt_id") == prompt_id:
                    result = {
                        "status": "error",
                        "prompt_id": prompt_id,
                        "node_id": msg_data.get("node_id"),
                        "node_type": msg_data.get("node_type"),
                        "message": msg_data.get("exception_message", "Unknown error"),
                    }
                    break

            elif msg_type == "execution_interrupted":
                if msg_data.get("prompt_id") == prompt_id:
                    result = {"status": "interrupted", "prompt_id": prompt_id}
                    break

    return result


def run_monitor(
    config: Config,
    client_id: str,
    prompt_id: str,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Synchronous wrapper for monitor_progress."""
    return asyncio.run(monitor_progress(config, client_id, prompt_id, on_progress))
