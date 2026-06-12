from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app_manager.models.discovery import DiscoveredApp


@dataclass(frozen=True)
class ScanIgnoreRule:
    label: str
    service_name: str | None = None
    executable_path: Path | None = None
    process_name: str | None = None
    local_address: str | None = None
    port: int | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any], base_dir: Path | None = None) -> "ScanIgnoreRule":
        base_dir = base_dir or Path.cwd()
        label = str(payload.get("label", "")).strip()
        if not label:
            raise ValueError("scan ignore rule label must be a non-empty string")

        executable_path_value = payload.get("executable_path")
        executable_path = None
        if executable_path_value is not None:
            executable_text = str(executable_path_value).strip()
            if executable_text:
                executable_path = _resolve_path(base_dir, executable_text)

        port_value = payload.get("port")
        port = None
        if port_value is not None:
            port = int(port_value)

        return cls(
            label=label,
            service_name=_optional_text(payload.get("service_name")),
            executable_path=executable_path,
            process_name=_optional_text(payload.get("process_name")),
            local_address=_optional_text(payload.get("local_address")),
            port=port,
        )

    @classmethod
    def from_discovered_app(cls, app: DiscoveredApp) -> "ScanIgnoreRule":
        return cls(
            label=_label_for_app(app),
            service_name=app.service_name,
            executable_path=app.executable_path,
            process_name=None if app.service_name else app.process_name,
            local_address=None if app.service_name else app.local_address,
            port=None if app.service_name else app.port,
        )

    def matches(self, app: DiscoveredApp) -> bool:
        if self.service_name is not None:
            return (app.service_name or "").strip().lower() == self.service_name.lower()

        if self.executable_path is not None:
            app_path = app.executable_path.resolve() if app.executable_path is not None else None
            if app_path != self.executable_path.resolve():
                return False
        elif app.executable_path is not None:
            return False

        if self.process_name is not None and app.process_name.lower() != self.process_name.lower():
            return False
        if self.local_address is not None and app.local_address != self.local_address:
            return False
        if self.port is not None and app.port != self.port:
            return False
        return True

    def to_dict(self, base_dir: Path | None = None) -> dict[str, Any]:
        payload = asdict(self)
        executable_path = payload.get("executable_path")
        if executable_path is not None:
            payload["executable_path"] = _serialize_path(Path(executable_path), base_dir)
        return payload


def filter_discovered_apps(apps: list[DiscoveredApp], ignore_rules: list[ScanIgnoreRule]) -> tuple[list[DiscoveredApp], int]:
    visible: list[DiscoveredApp] = []
    ignored_count = 0
    for app in apps:
        if any(rule.matches(app) for rule in ignore_rules):
            ignored_count += 1
            continue
        visible.append(app)
    return visible, ignored_count


def _label_for_app(app: DiscoveredApp) -> str:
    if app.service_name:
        return f"service:{app.service_name}"
    executable = str(app.executable_path) if app.executable_path else app.process_name
    return f"{executable} @ {app.local_address}:{app.port}"


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _resolve_path(base_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _serialize_path(path: Path, base_dir: Path | None) -> str:
    if base_dir is None:
        return str(path)
    try:
        return str(path.resolve().relative_to(base_dir.resolve()))
    except ValueError:
        return str(path)
