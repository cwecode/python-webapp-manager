from __future__ import annotations

from pathlib import Path

from app_manager.core.config_checks import validate_app_config
from app_manager.models import AppConfig


def _make_config(tmp_path: Path, host: str) -> AppConfig:
    python_path = tmp_path / ".venv" / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("", encoding="utf-8")
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    return AppConfig(
        id="demo",
        display_name="Demo App",
        mode="dev",
        repo_path=repo_path,
        branch="main",
        python_path=python_path,
        venv_path=tmp_path / ".venv",
        entry_kind="uvicorn",
        entry_target="main:app",
        host=host,
        port=8000,
        health_url="http://127.0.0.1:8000/health",
        env_file=None,
        requirements_file=None,
        init_command=None,
        service_name="demo-service",
        log_dir=tmp_path / "logs",
        winsw_exe_path=tmp_path / "winsw.exe",
        autostart_prod=False,
    )


def test_validate_app_config_warns_when_host_is_loopback_only(tmp_path: Path) -> None:
    result = validate_app_config(_make_config(tmp_path, "127.0.0.1"), check_port=False, check_entry=False)

    assert any("loopback-only" in warning for warning in result.warnings)


def test_validate_app_config_allows_network_bind_host_without_loopback_warning(tmp_path: Path) -> None:
    result = validate_app_config(_make_config(tmp_path, "0.0.0.0"), check_port=False, check_entry=False)

    assert not any("loopback-only" in warning for warning in result.warnings)
