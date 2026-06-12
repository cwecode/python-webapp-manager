from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from app_manager.core.controller import AppController
from app_manager.core.discovery import WindowsAppDiscovery
from app_manager.core.health import HealthChecker
from app_manager.core.installation import InstallationManager
from app_manager.core.process_runner import ProcessRunner
from app_manager.core.service_runner import ServiceRunner
from app_manager.core.updater import AppUpdater
from app_manager.models import ConfigValidationError, ManagerConfig
from app_manager.ui.main_window import MainWindow
from app_manager.ui.manager_settings_dialog import ManagerSettingsDialog


def main() -> int:
    root_dir = Path(__file__).resolve().parent.parent
    app = QApplication(sys.argv)
    manager_config_path = root_dir / "configs" / "manager.json"
    installation_manager = InstallationManager(manager_config_path, root_dir)
    try:
        manager_config = installation_manager.load_or_default()
    except (ConfigValidationError, OSError, ValueError) as exc:
        QMessageBox.critical(None, "App Manager", f"Failed to load manager config:\n{exc}")
        return 1

    if installation_manager.setup_required(manager_config):
        manager_config = _run_initial_setup(manager_config, installation_manager)
        if manager_config is None:
            return 0

    window = MainWindow(
        manager_config=manager_config,
        manager_config_path=manager_config_path,
        installation_manager=installation_manager,
        controller_factory=_build_controller,
    )
    window.show()
    return app.exec()


def _run_initial_setup(
    manager_config: ManagerConfig,
    installation_manager: InstallationManager,
) -> ManagerConfig | None:
    dialog = ManagerSettingsDialog(
        manager_config,
        base_dir=installation_manager.base_dir,
        setup_mode=True,
        allow_uninstall=False,
        parent=None,
    )
    if dialog.exec() != dialog.DialogCode.Accepted or dialog.selected_config is None:
        return None

    selected_config = dialog.selected_config
    try:
        installation_manager.ensure_layout(selected_config)
        installation_manager.save(selected_config)
    except OSError as exc:
        QMessageBox.critical(None, "App Manager", f"Failed to complete initial setup:\n{exc}")
        return None
    return selected_config


def _build_controller(manager_config: ManagerConfig) -> AppController:
    process_runner = ProcessRunner(manager_config.runtime_dir)
    service_runner = ServiceRunner(manager_config.runtime_dir)
    updater = AppUpdater()
    health_checker = HealthChecker()
    discovery = WindowsAppDiscovery(
        default_winsw_path=manager_config.winsw_exe_path,
        default_logs_root=manager_config.logs_dir,
    )
    return AppController(
        process_runner=process_runner,
        service_runner=service_runner,
        updater=updater,
        health_checker=health_checker,
        discovery=discovery,
    )
