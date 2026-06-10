from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app_manager.models.config import ConfigValidationError


@dataclass(frozen=True)
class ManagerConfig:
    apps_dir: Path
    runtime_dir: Path

    @classmethod
    def from_dict(cls, payload: dict[str, Any], base_dir: Path) -> "ManagerConfig":
        errors: list[str] = []
        apps_dir = payload.get("apps_dir")
        runtime_dir = payload.get("runtime_dir")

        if not isinstance(apps_dir, str) or not apps_dir.strip():
            errors.append("apps_dir must be a non-empty string")
        if not isinstance(runtime_dir, str) or not runtime_dir.strip():
            errors.append("runtime_dir must be a non-empty string")
        if errors:
            raise ConfigValidationError(errors)

        return cls(
            apps_dir=_resolve_path(base_dir, apps_dir),
            runtime_dir=_resolve_path(base_dir, runtime_dir),
        )

    @classmethod
    def load(cls, path: Path, base_dir: Path | None = None) -> "ManagerConfig":
        payload = json.loads(path.read_text(encoding="utf-8"))
        resolved_base = base_dir or path.parent
        try:
            return cls.from_dict(payload, resolved_base)
        except ConfigValidationError as exc:
            raise ConfigValidationError([f"{path.name}: {error}" for error in exc.errors]) from exc


def _resolve_path(base_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()
