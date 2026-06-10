from __future__ import annotations

import json
from pathlib import Path

import pytest

from app_manager.core.registry import AppRegistry
from app_manager.models import ConfigValidationError


def _write_config(path: Path, **overrides: object) -> None:
    payload = {
        "id": "demo",
        "display_name": "Demo App",
        "mode": "both",
        "repo_path": str(path.parent),
        "branch": "main",
        "python_path": r"C:\Python39\python.exe",
        "venv_path": r"C:\Python39",
        "entry_kind": "uvicorn",
        "entry_target": "main:app",
        "host": "127.0.0.1",
        "port": 8000,
        "health_url": "http://127.0.0.1:8000/health",
        "env_file": None,
        "requirements_file": None,
        "init_command": None,
        "service_name": "demo-app",
        "log_dir": str(path.parent / "logs"),
        "winsw_exe_path": r"C:\tools\WinSW-x64.exe",
        "autostart_prod": False,
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_registry_loads_valid_config(tmp_path: Path) -> None:
    config_dir = tmp_path / "apps"
    config_dir.mkdir()
    _write_config(config_dir / "demo.json")

    registry = AppRegistry(config_dir)
    configs = registry.load_all()

    assert len(configs) == 1
    assert configs[0].id == "demo"
    assert configs[0].port == 8000


def test_registry_rejects_missing_required_field(tmp_path: Path) -> None:
    config_dir = tmp_path / "apps"
    config_dir.mkdir()
    _write_config(config_dir / "demo.json")
    path = config_dir / "demo.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("service_name")
    path.write_text(json.dumps(payload), encoding="utf-8")

    registry = AppRegistry(config_dir)

    with pytest.raises(ConfigValidationError) as exc:
        registry.load_all()

    assert "missing required field 'service_name'" in str(exc.value)


def test_registry_rejects_invalid_port(tmp_path: Path) -> None:
    config_dir = tmp_path / "apps"
    config_dir.mkdir()
    _write_config(config_dir / "demo.json", port=70000)

    registry = AppRegistry(config_dir)

    with pytest.raises(ConfigValidationError) as exc:
        registry.load_all()

    assert "port must be an integer between 1 and 65535" in str(exc.value)


def test_registry_resolves_relative_paths_from_config_dir(tmp_path: Path) -> None:
    config_dir = tmp_path / "configs" / "apps"
    config_dir.mkdir(parents=True)
    _write_config(
        config_dir / "demo.json",
        repo_path="..\\..\\repo",
        python_path="..\\..\\.venv\\Scripts\\python.exe",
        venv_path="..\\..\\.venv",
        log_dir="..\\..\\logs\\demo",
        winsw_exe_path="..\\..\\tools\\WinSW-x64.exe",
    )

    registry = AppRegistry(config_dir)
    config = registry.load_all()[0]

    assert config.repo_path == (config_dir / ".." / ".." / "repo").resolve()
    assert config.python_path == (config_dir / ".." / ".." / ".venv" / "Scripts" / "python.exe").resolve()
    assert config.log_dir == (config_dir / ".." / ".." / "logs" / "demo").resolve()
