from __future__ import annotations

import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app_manager.core.health import normalize_health_url
from app_manager.core.subprocess_utils import run_capture
from app_manager.models import AppConfig


@dataclass(frozen=True)
class ConfigCheckResult:
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_app_config(config: AppConfig, *, check_port: bool = True, check_entry: bool = True) -> ConfigCheckResult:
    errors: list[str] = []
    warnings: list[str] = []

    if config.mode == "observed":
        _check_health_hint(config, warnings)
        return ConfigCheckResult(errors=errors, warnings=warnings)

    if not config.repo_path.exists():
        errors.append(f"repo_path not found: {config.repo_path}")
    if not config.venv_path.exists():
        errors.append(f"venv_path not found: {config.venv_path}")
    if not config.python_path.exists():
        errors.append(f"python_path not found: {config.python_path}")
    if config.mode in {"prod", "both"} and not config.winsw_exe_path.exists():
        warnings.append(f"WinSW executable not found yet: {config.winsw_exe_path}")

    if check_entry and config.repo_path.exists() and config.python_path.exists():
        entry_error = _check_entry_target(config)
        if entry_error:
            errors.append(entry_error)

    if check_port and _is_port_in_use(config.host, config.port):
        warnings.append(f"port appears to be in use: {config.host}:{config.port}")

    _check_health_hint(config, warnings)
    return ConfigCheckResult(errors=errors, warnings=warnings)


def _check_entry_target(config: AppConfig) -> str | None:
    module_name, separator, attribute_name = config.entry_target.partition(":")
    if not separator or not module_name.strip() or not attribute_name.strip():
        return "entry_target must use module:attribute format"

    script = (
        "import importlib; "
        f"module = importlib.import_module({module_name!r}); "
        f"getattr(module, {attribute_name!r})"
    )
    try:
        result = run_capture(
            [str(config.python_path), "-c", script],
            cwd=config.repo_path,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return "entry_target import timed out after 10 seconds"
    if result.returncode == 0:
        return None
    detail = result.stderr.strip() or result.stdout.strip() or "entry target import failed"
    return f"entry_target could not be imported: {detail}"


def _is_port_in_use(host: str, port: int) -> bool:
    bind_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((bind_host, port)) == 0


def _check_health_hint(config: AppConfig, warnings: list[str]) -> None:
    if config.health_url is None:
        warnings.append("health_url is not configured")
        return
    if normalize_health_url(config.health_url) != config.health_url:
        warnings.append("health_url had no scheme; http:// will be assumed")
