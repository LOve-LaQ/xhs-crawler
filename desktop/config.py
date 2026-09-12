from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


def config_path() -> Path:
    root = Path(os.environ.get("APPDATA", Path.home())) / "XHS Insight"
    root.mkdir(parents=True, exist_ok=True)
    return root / "config.json"


@dataclass
class AppSettings:
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    bridge_url: str = "ws://localhost:9333"
    workspace_dir: str = ""

    @classmethod
    def load(cls) -> AppSettings:
        path = config_path()
        if not path.exists():
            return cls(
                deepseek_api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
                deepseek_base_url=os.environ.get("DEEPSEEK_BASE_URL", cls.deepseek_base_url),
                deepseek_model=os.environ.get("DEEPSEEK_MODEL", cls.deepseek_model),
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        return cls(**{key: data[key] for key in asdict(cls()) if key in data})

    def save(self) -> None:
        config_path().write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )
