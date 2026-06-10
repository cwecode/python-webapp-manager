from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app_manager.models import ActionResult, AppConfig, LastAction


class RuntimeStore:
    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = runtime_root
        self.runtime_root.mkdir(parents=True, exist_ok=True)

    def app_dir(self, config: AppConfig) -> Path:
        path = self.runtime_root / config.id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def dev_state_path(self, config: AppConfig) -> Path:
        return self.app_dir(config) / "dev_state.json"

    def last_action_path(self, config: AppConfig) -> Path:
        return self.app_dir(config) / "last_action.json"

    def write_last_action(self, config: AppConfig, action_name: str, result: ActionResult) -> LastAction:
        action = LastAction(
            name=action_name,
            ok=result.ok,
            message=result.message,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self.last_action_path(config).write_text(
            json.dumps(action.to_dict(), indent=2),
            encoding="utf-8",
        )
        return action

    def read_last_action(self, config: AppConfig) -> LastAction | None:
        path = self.last_action_path(config)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return LastAction.from_dict(payload)
