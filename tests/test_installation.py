from __future__ import annotations

from pathlib import Path

from app_manager.core.installation import InstallationManager
from app_manager.models import ManagerConfig


def test_ensure_layout_creates_managed_directories_and_marker(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))
    config_path = tmp_path / "configs" / "manager.json"
    installation_manager = InstallationManager(config_path, tmp_path)
    manager_config = ManagerConfig.default(tmp_path).with_paths(tmp_path / "configs" / "apps", tmp_path / "install", True)

    installation_manager.ensure_layout(manager_config)

    assert manager_config.apps_dir.exists()
    assert manager_config.install_dir.exists()
    assert manager_config.runtime_dir.exists()
    assert manager_config.tools_dir.exists()
    assert manager_config.logs_dir.exists()
    assert (manager_config.install_dir / ".python-webapp-manager-installed").exists()


def test_uninstall_managed_assets_removes_only_managed_directories(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))
    config_path = tmp_path / "configs" / "manager.json"
    installation_manager = InstallationManager(config_path, tmp_path)
    manager_config = ManagerConfig.default(tmp_path).with_paths(tmp_path / "install" / "apps", tmp_path / "install", True)

    installation_manager.ensure_layout(manager_config)
    (manager_config.runtime_dir / "demo").mkdir(parents=True)
    (manager_config.runtime_dir / "demo" / "state.json").write_text("{}", encoding="utf-8")
    (manager_config.tools_dir / "WinSW-x64.exe").write_text("", encoding="utf-8")
    (manager_config.logs_dir / "demo").mkdir(parents=True)
    (manager_config.logs_dir / "demo" / "stdout.log").write_text("", encoding="utf-8")
    manager_config.apps_dir.mkdir(parents=True, exist_ok=True)
    (manager_config.apps_dir / "demo.json").write_text("{}", encoding="utf-8")

    installation_manager.uninstall_managed_assets(manager_config)

    assert not manager_config.install_dir.exists()
    assert not manager_config.runtime_dir.exists()
    assert not manager_config.tools_dir.exists()
    assert not manager_config.logs_dir.exists()
    assert not manager_config.apps_dir.exists()


def test_setup_required_when_config_not_initialized_or_layout_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))
    config_path = tmp_path / "configs" / "manager.json"
    installation_manager = InstallationManager(config_path, tmp_path)
    manager_config = ManagerConfig.default(tmp_path)

    assert installation_manager.setup_required(manager_config) is True

    initialized_config = manager_config.with_paths(manager_config.apps_dir, tmp_path / "install", True)
    installation_manager.ensure_layout(initialized_config)

    assert installation_manager.setup_required(initialized_config) is False
