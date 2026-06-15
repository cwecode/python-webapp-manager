from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

AppMode = Literal["dev", "prod", "both", "observed"]
EntryKind = Literal["waitress", "uvicorn"]


class ConfigValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass
class AppConfig:
    id: str
    display_name: str
    mode: AppMode
    repo_path: Path
    branch: str
    python_path: Path
    venv_path: Path
    entry_kind: EntryKind
    entry_target: str
    host: str
    port: int
    health_url: str | None
    env_file: Path | None
    requirements_file: Path | None
    init_command: str | None
    service_name: str
    log_dir: Path
    winsw_exe_path: Path
    autostart_prod: bool

    @classmethod
    def from_dict(cls, payload: dict[str, Any], base_dir: Path | None = None) -> "AppConfig":
        errors: list[str] = []
        required = [
            "id",
            "display_name",
            "mode",
            "repo_path",
            "branch",
            "python_path",
            "venv_path",
            "entry_kind",
            "entry_target",
            "host",
            "port",
            "service_name",
            "log_dir",
            "winsw_exe_path",
            "autostart_prod",
        ]
        for field_name in required:
            if field_name not in payload:
                errors.append(f"missing required field '{field_name}'")

        if errors:
            raise ConfigValidationError(errors)

        mode = payload["mode"]
        if mode not in {"dev", "prod", "both", "observed"}:
            errors.append("mode must be one of: dev, prod, both, observed")

        entry_kind = payload["entry_kind"]
        if entry_kind not in {"waitress", "uvicorn"}:
            errors.append("entry_kind must be one of: waitress, uvicorn")

        port = payload["port"]
        if not isinstance(port, int) or not (1 <= port <= 65535):
            errors.append("port must be an integer between 1 and 65535")

        autostart_prod = payload["autostart_prod"]
        if not isinstance(autostart_prod, bool):
            errors.append("autostart_prod must be a boolean")

        for text_field in ("id", "display_name", "branch", "entry_target", "host", "service_name"):
            value = payload.get(text_field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{text_field} must be a non-empty string")

        for path_field in ("repo_path", "python_path", "venv_path", "log_dir", "winsw_exe_path"):
            value = payload.get(path_field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{path_field} must be a non-empty string")

        health_url = payload.get("health_url")
        if health_url is not None and (not isinstance(health_url, str) or not health_url.strip()):
            errors.append("health_url must be a non-empty string when provided")

        for optional_path_field in ("env_file", "requirements_file"):
            value = payload.get(optional_path_field)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                errors.append(f"{optional_path_field} must be a non-empty string when provided")

        init_command = payload.get("init_command")
        if init_command is not None and (not isinstance(init_command, str) or not init_command.strip()):
            errors.append("init_command must be a non-empty string when provided")

        if errors:
            raise ConfigValidationError(errors)

        requirements_file = payload.get("requirements_file")
        env_file = payload.get("env_file")
        resolved_base = base_dir or Path.cwd()

        return cls(
            id=payload["id"].strip(),
            display_name=payload["display_name"].strip(),
            mode=mode,
            repo_path=_resolve_path(resolved_base, payload["repo_path"]),
            branch=payload["branch"].strip(),
            python_path=_resolve_path(resolved_base, payload["python_path"]),
            venv_path=_resolve_path(resolved_base, payload["venv_path"]),
            entry_kind=entry_kind,
            entry_target=payload["entry_target"].strip(),
            host=payload["host"].strip(),
            port=port,
            health_url=health_url.strip() if isinstance(health_url, str) else None,
            env_file=_resolve_path(resolved_base, env_file) if env_file else None,
            requirements_file=_resolve_path(resolved_base, requirements_file) if requirements_file else None,
            init_command=init_command.strip() if isinstance(init_command, str) else None,
            service_name=payload["service_name"].strip(),
            log_dir=_resolve_path(resolved_base, payload["log_dir"]),
            winsw_exe_path=_resolve_path(resolved_base, payload["winsw_exe_path"]),
            autostart_prod=autostart_prod,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, Path):
                payload[key] = str(value)
        return payload


def _resolve_path(base_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()
