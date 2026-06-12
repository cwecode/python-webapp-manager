from __future__ import annotations

import json
import os
import platform
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from app_manager.models.config import ConfigValidationError
from app_manager.models.scan_ignore import ScanIgnoreRule


@dataclass(frozen=True)
class ManagerConfig:
    apps_dir: Path
    install_dir: Path
    runtime_dir: Path
    tools_dir: Path
    logs_dir: Path
    winsw_exe_path: Path
    scan_ignore_rules: tuple[ScanIgnoreRule, ...] = ()
    initialized: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any], base_dir: Path) -> "ManagerConfig":
        errors: list[str] = []
        apps_dir = payload.get("apps_dir")
        install_dir_value = payload.get("install_dir")
        runtime_dir_value = payload.get("runtime_dir")
        tools_dir_value = payload.get("tools_dir")
        logs_dir_value = payload.get("logs_dir")
        winsw_exe_path_value = payload.get("winsw_exe_path")
        scan_ignore_rules_value = payload.get("scan_ignore_rules", [])
        initialized = payload.get("initialized", False)

        if not isinstance(apps_dir, str) or not apps_dir.strip():
            errors.append("apps_dir must be a non-empty string")
        if install_dir_value is not None and (not isinstance(install_dir_value, str) or not install_dir_value.strip()):
            errors.append("install_dir must be a non-empty string when provided")
        if runtime_dir_value is not None and (not isinstance(runtime_dir_value, str) or not runtime_dir_value.strip()):
            errors.append("runtime_dir must be a non-empty string when provided")
        if tools_dir_value is not None and (not isinstance(tools_dir_value, str) or not tools_dir_value.strip()):
            errors.append("tools_dir must be a non-empty string when provided")
        if logs_dir_value is not None and (not isinstance(logs_dir_value, str) or not logs_dir_value.strip()):
            errors.append("logs_dir must be a non-empty string when provided")
        if winsw_exe_path_value is not None and (
            not isinstance(winsw_exe_path_value, str) or not winsw_exe_path_value.strip()
        ):
            errors.append("winsw_exe_path must be a non-empty string when provided")
        if not isinstance(scan_ignore_rules_value, list):
            errors.append("scan_ignore_rules must be a list when provided")
        if not isinstance(initialized, bool):
            errors.append("initialized must be a boolean")
        if errors:
            raise ConfigValidationError(errors)

        install_dir = (
            _resolve_path(base_dir, install_dir_value)
            if isinstance(install_dir_value, str)
            else _derive_install_dir(base_dir, runtime_dir_value)
        )
        runtime_dir = (
            _resolve_path(base_dir, runtime_dir_value)
            if isinstance(runtime_dir_value, str)
            else install_dir / "runtime"
        )
        tools_dir = (
            _resolve_path(base_dir, tools_dir_value)
            if isinstance(tools_dir_value, str)
            else install_dir / "tools"
        )
        logs_dir = (
            _resolve_path(base_dir, logs_dir_value)
            if isinstance(logs_dir_value, str)
            else install_dir / "logs"
        )
        winsw_exe_path = (
            _resolve_path(base_dir, winsw_exe_path_value)
            if isinstance(winsw_exe_path_value, str)
            else tools_dir / "WinSW-x64.exe"
        )
        ignore_rules: list[ScanIgnoreRule] = []
        for index, item in enumerate(scan_ignore_rules_value):
            if not isinstance(item, dict):
                errors.append(f"scan_ignore_rules[{index}] must be an object")
                continue
            try:
                ignore_rules.append(ScanIgnoreRule.from_dict(item, base_dir))
            except (TypeError, ValueError) as exc:
                errors.append(f"scan_ignore_rules[{index}]: {exc}")
        if errors:
            raise ConfigValidationError(errors)

        return cls(
            apps_dir=_resolve_path(base_dir, apps_dir),
            install_dir=install_dir,
            runtime_dir=runtime_dir,
            tools_dir=tools_dir,
            logs_dir=logs_dir,
            winsw_exe_path=winsw_exe_path,
            scan_ignore_rules=tuple(ignore_rules),
            initialized=initialized,
        )

    @classmethod
    def load(cls, path: Path, base_dir: Path | None = None) -> "ManagerConfig":
        payload = json.loads(path.read_text(encoding="utf-8"))
        resolved_base = base_dir or path.parent
        try:
            return cls.from_dict(payload, resolved_base)
        except ConfigValidationError as exc:
            raise ConfigValidationError([f"{path.name}: {error}" for error in exc.errors]) from exc

    @classmethod
    def default(cls, base_dir: Path) -> "ManagerConfig":
        install_dir = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "python-webapp-manager"
        winsw_name = recommended_winsw_filename()
        return cls(
            apps_dir=install_dir / "apps",
            install_dir=install_dir,
            runtime_dir=install_dir / "runtime",
            tools_dir=install_dir / "tools",
            logs_dir=install_dir / "logs",
            winsw_exe_path=install_dir / "tools" / winsw_name,
            scan_ignore_rules=(),
            initialized=False,
        )

    def save(self, path: Path, base_dir: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(base_dir), indent=2), encoding="utf-8")

    def to_dict(self, base_dir: Path | None = None) -> dict[str, Any]:
        return {
            "apps_dir": _serialize_path(self.apps_dir, base_dir),
            "install_dir": _serialize_path(self.install_dir, base_dir),
            "runtime_dir": _serialize_path(self.runtime_dir, base_dir),
            "tools_dir": _serialize_path(self.tools_dir, base_dir),
            "logs_dir": _serialize_path(self.logs_dir, base_dir),
            "winsw_exe_path": _serialize_path(self.winsw_exe_path, base_dir),
            "scan_ignore_rules": [rule.to_dict(base_dir) for rule in self.scan_ignore_rules],
            "initialized": self.initialized,
        }

    def with_paths(self, apps_dir: Path, install_dir: Path, initialized: bool) -> "ManagerConfig":
        resolved_install_dir = install_dir.resolve()
        winsw_name = recommended_winsw_filename()
        return replace(
            self,
            apps_dir=apps_dir.resolve(),
            install_dir=resolved_install_dir,
            runtime_dir=resolved_install_dir / "runtime",
            tools_dir=resolved_install_dir / "tools",
            logs_dir=resolved_install_dir / "logs",
            winsw_exe_path=resolved_install_dir / "tools" / winsw_name,
            scan_ignore_rules=self.scan_ignore_rules,
            initialized=initialized,
        )


def _resolve_path(base_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _derive_install_dir(base_dir: Path, runtime_dir_value: Any) -> Path:
    if isinstance(runtime_dir_value, str) and runtime_dir_value.strip():
        return _resolve_path(base_dir, runtime_dir_value).parent
    return ManagerConfig.default(base_dir).install_dir


def _serialize_path(path: Path, base_dir: Path | None) -> str:
    if base_dir is None:
        return str(path)
    try:
        return str(path.resolve().relative_to(base_dir.resolve()))
    except ValueError:
        return str(path)


def recommended_winsw_filename() -> str:
    machine = platform.machine().lower()
    if "64" in machine or machine in {"amd64", "x86_64", "arm64"}:
        return "WinSW-x64.exe"
    return "WinSW-x86.exe"
