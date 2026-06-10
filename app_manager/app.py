from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from app_manager.core.controller import AppController
from app_manager.core.health import HealthChecker
from app_manager.core.process_runner import ProcessRunner
from app_manager.core.registry import AppRegistry
from app_manager.core.service_runner import ServiceRunner
from app_manager.core.updater import AppUpdater
from app_manager.models import ConfigValidationError, ManagerConfig
from app_manager.ui.main_window import MainWindow


def main() -> int:
    root_dir = Path(__file__).resolve().parent.parent
    app = QApplication(sys.argv)
    manager_config_path = root_dir / "configs" / "manager.json"
    try:
        manager_config = ManagerConfig.load(manager_config_path, base_dir=root_dir)
    except (ConfigValidationError, OSError, ValueError) as exc:
        QMessageBox.critical(None, "App Manager", f"Failed to load manager config:\n{exc}")
        return 1

    registry = AppRegistry(manager_config.apps_dir)
    process_runner = ProcessRunner(manager_config.runtime_dir)
    service_runner = ServiceRunner(manager_config.runtime_dir)
    updater = AppUpdater()
    health_checker = HealthChecker()
    controller = AppController(
        process_runner=process_runner,
        service_runner=service_runner,
        updater=updater,
        health_checker=health_checker,
    )

    window = MainWindow(
        registry=registry,
        controller=controller,
    )
    window.show()
    return app.exec()
