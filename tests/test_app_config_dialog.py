from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app_manager.models import AppConfig, ManagerConfig
from app_manager.ui.app_config_dialog import AppConfigDialog


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _manager_config(tmp_path: Path) -> ManagerConfig:
    return ManagerConfig(
        apps_dir=tmp_path / "apps",
        install_dir=tmp_path,
        runtime_dir=tmp_path / "runtime",
        tools_dir=tmp_path / "tools",
        logs_dir=tmp_path / "logs",
        winsw_exe_path=tmp_path / "tools" / "WinSW-x64.exe",
        scan_ignore_rules=(),
        initialized=True,
    )


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        id="demo",
        display_name="Demo App",
        mode="both",
        repo_path=tmp_path / "repo",
        branch="release",
        python_path=tmp_path / ".venv" / "Scripts" / "python.exe",
        venv_path=tmp_path / ".venv",
        entry_kind="waitress",
        entry_target="server:app",
        host="0.0.0.0",
        port=9090,
        health_url="http://127.0.0.1:9090/health",
        env_file=None,
        requirements_file=tmp_path / "requirements.txt",
        init_command=None,
        service_name="demo-service",
        log_dir=tmp_path / "logs" / "demo",
        winsw_exe_path=tmp_path / "tools" / "WinSW-x64.exe",
        autostart_prod=True,
    )


def test_edit_dialog_shows_existing_config_without_applying_template_defaults(tmp_path: Path) -> None:
    _app()
    dialog = AppConfigDialog(_manager_config(tmp_path), existing_config=_config(tmp_path))

    assert dialog._combo_box("template").currentText() == "Current config"
    assert dialog._combo_box("template").isEnabled() is False
    assert dialog._combo_box("mode").currentText() == "both"
    assert dialog._combo_box("entry_kind").currentText() == "waitress"
    assert dialog._combo_box("entry_target").currentText() == "server:app"
    assert dialog._line_edit("host").text() == "0.0.0.0"
    assert dialog._spin_box("port").value() == 9090
