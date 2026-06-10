from __future__ import annotations

import json
from pathlib import Path

from app_manager.models.config import AppConfig, ConfigValidationError


class AppRegistry:
    def __init__(self, config_dir: Path) -> None:
        self.config_dir = config_dir
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def load_all(self) -> list[AppConfig]:
        configs: list[AppConfig] = []
        for path in sorted(self.config_dir.glob("*.json")):
            configs.append(self.load_file(path))
        return configs

    def load_file(self, path: Path) -> AppConfig:
        payload = json.loads(path.read_text(encoding="utf-8"))
        try:
            return AppConfig.from_dict(payload, base_dir=path.parent)
        except ConfigValidationError as exc:
            raise ConfigValidationError([f"{path.name}: {error}" for error in exc.errors]) from exc

    def save(self, config: AppConfig) -> Path:
        path = self.config_dir / f"{config.id}.json"
        path.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
        return path

    def get(self, app_id: str) -> AppConfig | None:
        path = self.config_dir / f"{app_id}.json"
        if not path.exists():
            return None
        return self.load_file(path)
