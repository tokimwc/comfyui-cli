"""Configuration management for ComfyUI CLI."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8188
CONFIG_DIR = Path.home() / ".comfyui-cli"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class Config:
    """ComfyUI CLI configuration."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    output_dir: str = ""
    input_dir: str = ""

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def ws_url(self) -> str:
        return f"ws://{self.host}:{self.port}/ws"

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps(
                {"host": self.host, "port": self.port, "output_dir": self.output_dir, "input_dir": self.input_dir},
                indent=2,
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls) -> Config:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        return cls()
