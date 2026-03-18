"""ComfyUI REST API client."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import httpx

from .config import Config


class ComfyUIClient:
    """HTTP client for ComfyUI REST API."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config.load()
        self.client_id = str(uuid.uuid4())
        self._http = httpx.Client(base_url=self.config.base_url, timeout=30.0)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> ComfyUIClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ── System ──────────────────────────────────────────────

    def is_alive(self) -> bool:
        """Check if ComfyUI server is reachable."""
        try:
            r = self._http.get("/system_stats")
            return r.status_code == 200
        except httpx.ConnectError:
            return False

    def system_stats(self) -> dict[str, Any]:
        """Get system statistics (OS, RAM, GPU, versions)."""
        return self._http.get("/system_stats").json()

    # ── Models ──────────────────────────────────────────────

    def model_folders(self) -> list[str]:
        """List available model folder types."""
        return self._http.get("/models").json()

    def models(self, folder: str) -> list[str]:
        """List models in a specific folder."""
        return self._http.get(f"/models/{folder}").json()

    # ── Nodes ───────────────────────────────────────────────

    def object_info(self, node_class: str | None = None) -> dict[str, Any]:
        """Get node type information."""
        path = f"/object_info/{node_class}" if node_class else "/object_info"
        return self._http.get(path).json()

    # ── Queue & Execution ───────────────────────────────────

    def get_queue(self) -> dict[str, Any]:
        """Get current queue status."""
        return self._http.get("/queue").json()

    def queue_prompt(self, prompt: dict[str, Any], extra_data: dict | None = None) -> dict[str, Any]:
        """Submit a prompt for execution.

        Args:
            prompt: API-format prompt (node_id -> node_config mapping).
            extra_data: Optional extra data (e.g., workflow GUI JSON for history).

        Returns:
            Response with prompt_id and other info.
        """
        payload: dict[str, Any] = {
            "prompt": prompt,
            "client_id": self.client_id,
        }
        if extra_data:
            payload["extra_data"] = extra_data
        r = self._http.post("/prompt", json=payload)
        r.raise_for_status()
        return r.json()

    def clear_queue(self) -> None:
        """Clear the execution queue."""
        self._http.post("/queue", json={"clear": True})

    def interrupt(self) -> None:
        """Interrupt current execution."""
        self._http.post("/interrupt")

    def free_memory(self, unload_models: bool = True, free_memory: bool = True) -> None:
        """Free GPU memory and optionally unload models."""
        self._http.post("/free", json={"unload_models": unload_models, "free_memory": free_memory})

    # ── History ─────────────────────────────────────────────

    def history(self, prompt_id: str | None = None, max_items: int = 20) -> dict[str, Any]:
        """Get execution history."""
        if prompt_id:
            return self._http.get(f"/history/{prompt_id}").json()
        return self._http.get("/history", params={"max_items": max_items}).json()

    def clear_history(self) -> None:
        """Clear execution history."""
        self._http.post("/history", json={"clear": True})

    # ── Images ──────────────────────────────────────────────

    def upload_image(self, file_path: str | Path, subfolder: str = "", image_type: str = "input", overwrite: bool = False) -> dict[str, Any]:
        """Upload an image to ComfyUI."""
        path = Path(file_path)
        with path.open("rb") as f:
            r = self._http.post(
                "/upload/image",
                files={"image": (path.name, f, "image/png")},
                data={
                    "subfolder": subfolder,
                    "type": image_type,
                    "overwrite": str(overwrite).lower(),
                },
            )
        r.raise_for_status()
        return r.json()

    def view_image(self, filename: str, subfolder: str = "", image_type: str = "output") -> bytes:
        """Download an image from ComfyUI."""
        r = self._http.get(
            "/view",
            params={"filename": filename, "subfolder": subfolder, "type": image_type},
        )
        r.raise_for_status()
        return r.content

    # ── Embeddings & Extensions ─────────────────────────────

    def embeddings(self) -> list[str]:
        """List available embeddings."""
        return self._http.get("/embeddings").json()

    def extensions(self) -> list[str]:
        """List available extensions."""
        return self._http.get("/extensions").json()

    # ── Internal ────────────────────────────────────────────

    def folder_paths(self) -> dict[str, Any]:
        """Get folder path mappings (internal API)."""
        return self._http.get("/internal/folder_paths").json()

    def list_files(self, directory_type: str = "output") -> list[Any]:
        """List files in a directory (output/input/temp)."""
        return self._http.get(f"/internal/files/{directory_type}").json()
