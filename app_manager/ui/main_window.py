from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app_manager.core.installation import InstallationManager
from app_manager.core.controller import AppController
from app_manager.core.registry import AppRegistry
from app_manager.models import (
    ActionResult,
    AppConfig,
    AppSnapshot,
    ConfigValidationError,
    ManagerConfig,
    ScanIgnoreRule,
    filter_discovered_apps,
)
from app_manager.ui.app_config_dialog import AppConfigDialog
from app_manager.ui.discovery_dialog import DiscoveryDialog
from app_manager.ui.log_viewer import LogViewer
from app_manager.ui.manager_settings_dialog import ManagerSettingsDialog
from app_manager.ui.theme import apply_dialog_style


@dataclass
class AppContext:
    config: AppConfig
    snapshot: AppSnapshot


class ScanWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self.controller = controller

    def run(self) -> None:
        try:
            self.finished.emit(self.controller.discover_apps())
        except Exception as exc:
            self.failed.emit(str(exc))


class RefreshWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, registry: AppRegistry, controller: AppController, selected_app_id: str | None) -> None:
        super().__init__()
        self.registry = registry
        self.controller = controller
        self.selected_app_id = selected_app_id

    def run(self) -> None:
        try:
            apps = self.registry.load_all()
            snapshots = {config.id: self.controller.snapshot(config) for config in apps}
            self.finished.emit((apps, snapshots, self.selected_app_id))
        except Exception as exc:
            self.failed.emit(str(exc))


class ActionWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, action_name: str, config: AppConfig, handler: Callable[[AppConfig], ActionResult]) -> None:
        super().__init__()
        self.action_name = action_name
        self.config = config
        self.handler = handler

    def run(self) -> None:
        try:
            self.finished.emit((self.action_name, self.handler(self.config)))
        except Exception as exc:
            self.failed.emit(str(exc))


AUTO_REFRESH_INTERVAL_MS = 30_000


class MainWindow(QMainWindow):
    def __init__(
        self,
        manager_config: ManagerConfig,
        manager_config_path: Path,
        installation_manager: InstallationManager,
        controller_factory: Callable[[ManagerConfig], AppController],
    ) -> None:
        super().__init__()
        self.manager_config = manager_config
        self.manager_config_path = manager_config_path
        self.installation_manager = installation_manager
        self._controller_factory = controller_factory
        self.registry = AppRegistry(manager_config.apps_dir)
        self.controller = controller_factory(manager_config)
        self._apps: list[AppConfig] = []
        self._snapshots: dict[str, AppSnapshot] = {}
        self._scan_thread: QThread | None = None
        self._scan_worker: ScanWorker | None = None
        self._scan_progress: QProgressDialog | None = None
        self._refresh_thread: QThread | None = None
        self._refresh_worker: RefreshWorker | None = None
        self._refresh_show_errors = False
        self._action_thread: QThread | None = None
        self._action_worker: ActionWorker | None = None
        self._action_progress: QProgressDialog | None = None
        self._close_requested = False

        self.setWindowTitle("App Manager")
        self.resize(1320, 760)
        self.setMinimumSize(820, 520)
        _apply_app_style(self)

        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        splitter.addWidget(left_panel)

        self.app_table = QTableWidget(0, 4)
        self.app_table.setHorizontalHeaderLabels(["", "App", "Runtime", "Git"])
        self.app_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.app_table.setSelectionMode(QTableWidget.SingleSelection)
        self.app_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.app_table.setSortingEnabled(True)
        self.app_table.setAlternatingRowColors(True)
        self.app_table.verticalHeader().setVisible(False)
        self.app_table.verticalHeader().setDefaultSectionSize(34)
        self.app_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.app_table.setMinimumWidth(240)
        self.app_table.setMaximumWidth(520)
        self.app_table.currentCellChanged.connect(lambda row, _column, _previous_row, _previous_column: self._render_current_app(row))
        header = self.app_table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        left_layout.addWidget(self.app_table, 3)

        logs_group = QGroupBox("Logs")
        logs_group.setObjectName("surface")
        logs_layout = QVBoxLayout(logs_group)
        logs_layout.setContentsMargins(10, 14, 10, 10)
        logs_layout.setSpacing(6)
        left_layout.addWidget(logs_group, 2)

        self.log_tabs = QTabWidget()
        self.log_tabs.setDocumentMode(True)
        logs_layout.addWidget(self.log_tabs)
        self.stdout_view = LogViewer()
        self.stderr_view = LogViewer()
        self.log_tabs.addTab(self.stdout_view, "stdout.log")
        self.log_tabs.addTab(self.stderr_view, "stderr.log")

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(16, 12, 12, 12)
        right_layout.setSpacing(10)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setWidget(right_panel)
        splitter.addWidget(right_scroll)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([430, 890])

        self.summary_label = QLabel("No app selected")
        self.summary_label.setObjectName("appTitle")
        self.summary_label.setWordWrap(True)

        link_row = QHBoxLayout()
        link_row.setContentsMargins(0, 0, 0, 0)
        link_row.setSpacing(12)
        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(4)
        title_stack.addWidget(self.summary_label)
        self.app_url_label = QLabel("")
        self.app_url_label.setObjectName("appUrl")
        self.app_url_label.setOpenExternalLinks(True)
        self.app_url_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        title_stack.addWidget(self.app_url_label)
        link_row.addLayout(title_stack, 1)
        self.open_app_button = QPushButton("Open App")
        self.open_app_button.setObjectName("openAppButton")
        self.open_app_button.clicked.connect(self.open_app)
        link_row.addWidget(self.open_app_button)
        right_layout.addLayout(link_row)

        cards_row = QGridLayout()
        cards_row.setHorizontalSpacing(8)
        cards_row.setVerticalSpacing(8)
        right_layout.addLayout(cards_row)
        self.runtime_card = _status_card("Runtime", "-")
        self.health_card = _status_card("Health", "-")
        self.git_card = _status_card("Git", "-")
        self.uptime_card = _status_card("Uptime", "-")
        cards_row.addWidget(self.runtime_card, 0, 0)
        cards_row.addWidget(self.health_card, 0, 1)
        cards_row.addWidget(self.git_card, 1, 0)
        cards_row.addWidget(self.uptime_card, 1, 1)

        detail_group = QGroupBox("Details")
        detail_group.setObjectName("surface")
        self.detail_layout = QFormLayout(detail_group)
        self.detail_layout.setContentsMargins(12, 14, 12, 12)
        self.detail_layout.setHorizontalSpacing(18)
        self.detail_layout.setVerticalSpacing(8)
        self.detail_layout.setLabelAlignment(Qt.AlignLeft)
        right_layout.addWidget(detail_group)

        app_actions = QGroupBox("App Process Controls")
        app_actions.setObjectName("surface")
        app_action_grid = QGridLayout(app_actions)
        app_action_grid.setContentsMargins(12, 14, 12, 12)
        app_action_grid.setHorizontalSpacing(8)
        app_action_grid.setVerticalSpacing(8)
        right_layout.addWidget(app_actions)

        service_actions = QGroupBox("Windows Service Controls")
        service_actions.setObjectName("surface")
        service_action_grid = QGridLayout(service_actions)
        service_action_grid.setContentsMargins(12, 14, 12, 12)
        service_action_grid.setHorizontalSpacing(8)
        service_action_grid.setVerticalSpacing(8)
        right_layout.addWidget(service_actions)

        settings_tools = QGroupBox("Workspace")
        settings_tools.setObjectName("surface")
        settings_grid = QGridLayout(settings_tools)
        settings_grid.setContentsMargins(12, 14, 12, 12)
        settings_grid.setHorizontalSpacing(8)
        settings_grid.setVerticalSpacing(8)
        right_layout.addWidget(settings_tools)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(lambda: self.reload_apps(show_errors=True))
        settings_grid.addWidget(self.refresh_button, 0, 0)

        self.add_app_button = QPushButton("Connect App")
        self.add_app_button.setToolTip("Add a Python web app with the guided wizard.")
        self.add_app_button.clicked.connect(self.add_app)
        settings_grid.addWidget(self.add_app_button, 0, 1)

        self.edit_app_button = QPushButton("Edit Config")
        self.edit_app_button.clicked.connect(self.edit_app)
        settings_grid.addWidget(self.edit_app_button, 0, 2)

        self.start_button = QPushButton("Start App Process")
        self.start_button.setToolTip("Start the app as a local Python process managed by App Manager.")
        self.start_button.clicked.connect(self.start_dev)
        app_action_grid.addWidget(self.start_button, 0, 0)

        self.stop_button = QPushButton("Stop App Process")
        self.stop_button.setToolTip("Stop the local Python process started or attached by App Manager.")
        self.stop_button.clicked.connect(self.stop_dev)
        app_action_grid.addWidget(self.stop_button, 0, 1)

        self.restart_button = QPushButton("Restart App Process")
        self.restart_button.setToolTip("Stop and start the local Python process again.")
        self.restart_button.clicked.connect(self.restart_dev)
        app_action_grid.addWidget(self.restart_button, 1, 0)

        self.stop_external_button = QPushButton("Stop External Listener")
        self.stop_external_button.setToolTip("Force stop an unmanaged process currently listening on this app's configured port.")
        self.stop_external_button.clicked.connect(self.stop_external_process)
        app_action_grid.addWidget(self.stop_external_button, 3, 0, 1, 2)

        self.install_service_button = QPushButton("Install Service")
        self.install_service_button.clicked.connect(self.install_service)
        service_action_grid.addWidget(self.install_service_button, 1, 0)

        self.uninstall_service_button = QPushButton("Uninstall Service")
        self.uninstall_service_button.clicked.connect(self.uninstall_service)
        service_action_grid.addWidget(self.uninstall_service_button, 2, 1)

        self.start_service_button = QPushButton("Start Service")
        self.start_service_button.clicked.connect(self.start_service)
        service_action_grid.addWidget(self.start_service_button, 1, 1)

        self.stop_service_button = QPushButton("Stop Service")
        self.stop_service_button.clicked.connect(self.stop_service)
        service_action_grid.addWidget(self.stop_service_button, 2, 0)

        self.restart_service_button = QPushButton("Restart Service")
        self.restart_service_button.clicked.connect(self.restart_service)
        service_action_grid.addWidget(self.restart_service_button, 0, 1)

        self.health_button = QPushButton("Recheck Health")
        self.health_button.setToolTip("Run the health check immediately instead of waiting for the next refresh.")
        self.health_button.clicked.connect(self.check_health)
        app_action_grid.addWidget(self.health_button, 1, 1)

        self.update_button = QPushButton("Update App")
        self.update_button.setToolTip("Pull the selected app from GitHub and restart the active runtime when needed.")
        self.update_button.clicked.connect(self.update_app)
        app_action_grid.addWidget(self.update_button, 2, 0, 1, 2)

        self.open_logs_button = QPushButton("Open Logs")
        self.open_logs_button.clicked.connect(self.open_logs)
        settings_grid.addWidget(self.open_logs_button, 1, 0)

        self.scan_button = QPushButton("Find Running Apps")
        self.scan_button.setToolTip("Scan local ports and services to import or diagnose existing apps.")
        self.scan_button.clicked.connect(self.scan_services)
        settings_grid.addWidget(self.scan_button, 1, 1)

        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self.open_settings)
        settings_grid.addWidget(self.settings_button, 1, 2)

        self.github_help_button = QPushButton("GitHub / Update Help")
        self.github_help_button.setToolTip("Explain how App Manager checks local installs against GitHub remotes.")
        self.github_help_button.clicked.connect(self.open_github_help)
        settings_grid.addWidget(self.github_help_button, 2, 0, 1, 3)

        self.self_update_button = QPushButton("Update App Manager")
        self.self_update_button.setToolTip("Pull the latest App Manager version from GitHub and reinstall it.")
        self.self_update_button.clicked.connect(self.update_app_manager)
        settings_grid.addWidget(self.self_update_button, 3, 0, 1, 3)
        _set_button_role(self.open_app_button, "primary")
        _set_button_role(self.start_button, "primary")
        _set_button_role(self.stop_button, "danger")
        _set_button_role(self.stop_external_button, "danger")
        _set_button_role(self.health_button, "secondary")
        _set_button_role(self.update_button, "warning")
        for button in (
            self.restart_button,
            self.install_service_button,
            self.start_service_button,
            self.stop_service_button,
            self.restart_service_button,
            self.refresh_button,
            self.add_app_button,
            self.edit_app_button,
            self.open_logs_button,
            self.scan_button,
            self.settings_button,
            self.github_help_button,
            self.self_update_button,
        ):
            _set_button_role(button, "secondary")
        _set_button_role(self.uninstall_service_button, "danger")

        self.scan_status_label = QLabel("Scan status: not started")
        self.scan_status_label.setObjectName("statusLine")
        self.scan_status_label.setWordWrap(True)
        right_layout.addWidget(self.scan_status_label)
        right_layout.addStretch(1)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(AUTO_REFRESH_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_current_view)
        self._poll_timer.start()

        self.reload_apps(show_errors=True)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._poll_timer.stop()
        if self._background_running():
            self._close_requested = True
            self.setEnabled(False)
            self.scan_status_label.setText("Waiting for the current background task to finish before closing...")
            if self._scan_progress is not None:
                self._scan_progress.setLabelText("Waiting for the current scan to finish before closing...")
            if self._action_progress is not None:
                self._action_progress.setLabelText("Waiting for the current action to finish before closing...")
            event.ignore()
            return
        super().closeEvent(event)

    def reload_apps(self, show_errors: bool) -> None:
        if self._refresh_thread is not None:
            return

        selected_app_id = self._selected_app_id()
        self._refresh_show_errors = show_errors
        self.refresh_button.setEnabled(False)
        self.scan_status_label.setText("Status: refreshing apps...")
        self._refresh_thread = QThread(self)
        self._refresh_worker = RefreshWorker(self.registry, self.controller, selected_app_id)
        self._refresh_worker.moveToThread(self._refresh_thread)
        self._refresh_thread.started.connect(self._refresh_worker.run)
        self._refresh_worker.finished.connect(self._on_refresh_finished)
        self._refresh_worker.failed.connect(self._on_refresh_failed)
        self._refresh_worker.finished.connect(self._refresh_thread.quit)
        self._refresh_worker.failed.connect(self._refresh_thread.quit)
        self._refresh_thread.finished.connect(self._cleanup_refresh)
        self._refresh_thread.start()

    def _on_refresh_finished(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 3:
            self._on_refresh_failed("refresh returned an unexpected result")
            return

        apps, snapshots, selected_app_id = payload
        self._apps = apps if isinstance(apps, list) else []
        self._snapshots = snapshots if isinstance(snapshots, dict) else {}
        selected_app_id = selected_app_id if isinstance(selected_app_id, str) else None

        self.app_table.setSortingEnabled(False)
        self.app_table.clearContents()
        self.app_table.setRowCount(len(self._apps))
        for index, config in enumerate(self._apps):
            snapshot = self._snapshots[config.id]
            self._set_app_table_row(index, config, snapshot)
        self.app_table.setSortingEnabled(True)
        self.app_table.sortItems(0, Qt.AscendingOrder)

        if self._apps:
            self._select_app_id(selected_app_id or self._apps[0].id)
        else:
            self.summary_label.setText(
                f"No apps connected yet. Use Connect App for a normal setup or Find Running Apps for existing processes. "
                f"Config folder: {self.registry.config_dir}"
            )
            self.app_url_label.setText("")
            self._reset_cards()
            self.stdout_view.set_log_path(None)
            self.stderr_view.set_log_path(None)
            self._sync_buttons(None, None)
        self.scan_status_label.setText("Status: ready")

    def _on_refresh_failed(self, message: str) -> None:
        self._apps = []
        self._snapshots = {}
        self.app_table.clearContents()
        self.app_table.setRowCount(0)
        self.app_url_label.setText("")
        self._reset_cards()
        self._sync_buttons(None, None)
        self.scan_status_label.setText(f"Status refresh failed: {message}")
        if self._refresh_show_errors:
            self._show_error("Configuration Error", message)

    def _cleanup_refresh(self) -> None:
        self.refresh_button.setEnabled(True)
        if self._refresh_worker is not None:
            self._refresh_worker.deleteLater()
            self._refresh_worker = None
        if self._refresh_thread is not None:
            self._refresh_thread.deleteLater()
            self._refresh_thread = None
        self._finish_pending_close()

    def start_dev(self) -> None:
        self._run_selected_action("Start App Process", self.controller.start_dev)

    def stop_dev(self) -> None:
        self._run_selected_action("Stop App Process", self.controller.stop_dev)

    def restart_dev(self) -> None:
        self._run_selected_action("Restart App Process", self.controller.restart_dev)

    def stop_external_process(self) -> None:
        self._run_selected_action("Stop External Listener", self.controller.stop_external_process)

    def check_health(self) -> None:
        self._run_selected_action("Recheck Health", self.controller.check_health)

    def update_app(self) -> None:
        self._run_selected_action("Update App", self.controller.update_app)

    def install_service(self) -> None:
        self._run_selected_action("Install Service", self.controller.install_service)

    def uninstall_service(self) -> None:
        self._run_selected_action("Uninstall Service", self.controller.uninstall_service)

    def start_service(self) -> None:
        self._run_selected_action("Start Service", self.controller.start_service)

    def stop_service(self) -> None:
        self._run_selected_action("Stop Service", self.controller.stop_service)

    def restart_service(self) -> None:
        self._run_selected_action("Restart Service", self.controller.restart_service)

    def open_logs(self) -> None:
        config = self._selected_config()
        if not config:
            return
        result = self.controller.open_logs(config)
        self._show_result(result.ok, result.message)
        self.reload_apps(show_errors=False)

    def open_app(self) -> None:
        config = self._selected_config()
        if not config:
            return
        QDesktopServices.openUrl(QUrl(self._app_url(config)))

    def open_settings(self) -> None:
        dialog = ManagerSettingsDialog(
            self.manager_config,
            base_dir=self.installation_manager.base_dir,
            setup_mode=False,
            allow_uninstall=True,
            parent=self,
        )
        if dialog.exec() != dialog.DialogCode.Accepted or dialog.selected_config is None:
            return

        if dialog.request_uninstall:
            self._uninstall_managed_assets(dialog.selected_config)
            return

        self._save_and_reload_manager_config(dialog.selected_config)

    def open_github_help(self) -> None:
        _show_github_help(self)

    def update_app_manager(self) -> None:
        root_dir = self.installation_manager.base_dir
        venv_python = root_dir / ".venv" / "Scripts" / "python.exe"
        venv_app_manager = root_dir / ".venv" / "Scripts" / "app-manager.exe"
        update_script = root_dir / "update-app-manager.cmd"
        if not (root_dir / ".git").exists():
            self._show_error("Update App Manager", f"App Manager root is not a Git repository:\n{root_dir}")
            return
        if not venv_python.exists():
            self._show_error("Update App Manager", f"Virtual environment Python not found:\n{venv_python}")
            return

        confirm = QMessageBox.question(
            self,
            "Update App Manager",
            "This opens a command window, pulls the latest App Manager version, reinstalls it, "
            "then starts App Manager again. The current window will close. Continue?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        script = f"""@echo off
title Update App Manager
cd /d "{root_dir}"
echo Updating App Manager in {root_dir}
echo.
echo [1/3] Pulling latest version from GitHub...
git pull
if errorlevel 1 goto failed
echo.
echo [2/3] Reinstalling package in .venv...
"{venv_python}" -m pip install -e .
if errorlevel 1 goto failed
echo.
echo [3/3] Starting App Manager...
start "" "{venv_app_manager}"
echo.
echo Update finished. You can close this window.
goto end

:failed
echo.
echo Update failed. Check the error above.
pause

:end
"""
        try:
            update_script.write_text(script, encoding="utf-8")
            subprocess.Popen(
                ["cmd.exe", "/k", str(update_script)],
                cwd=root_dir,
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
        except OSError as exc:
            self._show_error("Update App Manager", str(exc))
            return
        self.close()

    def add_app(self) -> None:
        dialog = AppConfigDialog(self.manager_config, parent=self)
        if dialog.exec() != dialog.DialogCode.Accepted or dialog.selected_config is None:
            return

        config = dialog.selected_config
        if self.registry.get(config.id) is not None:
            overwrite = QMessageBox.question(
                self,
                "Overwrite Config",
                f"A config with ID '{config.id}' already exists. Overwrite it?",
            )
            if overwrite != QMessageBox.StandardButton.Yes:
                return

        path = self.registry.save(config)
        QMessageBox.information(self, "Config Saved", f"Saved app config to {path}")
        self.reload_apps(show_errors=False)

    def edit_app(self) -> None:
        config = self._selected_config()
        if not config:
            return

        original_id = config.id
        dialog = AppConfigDialog(self.manager_config, existing_config=config, parent=self)
        if dialog.exec() != dialog.DialogCode.Accepted or dialog.selected_config is None:
            return

        updated_config = dialog.selected_config
        existing_config = self.registry.get(updated_config.id)
        if updated_config.id != original_id and existing_config is not None:
            overwrite = QMessageBox.question(
                self,
                "Overwrite Config",
                f"A config with ID '{updated_config.id}' already exists. Overwrite it?",
            )
            if overwrite != QMessageBox.StandardButton.Yes:
                return

        path = self.registry.save(updated_config, previous_id=original_id)
        QMessageBox.information(self, "Config Updated", f"Saved updated app config to {path}")
        self.reload_apps(show_errors=False)

    def scan_services(self) -> None:
        if self._scan_thread is not None:
            return

        self.scan_button.setEnabled(False)
        self.scan_status_label.setText("Scan status: scanning local ports and services...")
        self._scan_progress = QProgressDialog("Scanning local ports and services...", "", 0, 0, self)
        self._scan_progress.setWindowTitle("Find Running Apps")
        self._scan_progress.setCancelButton(None)
        self._scan_progress.setMinimumDuration(0)
        self._scan_progress.setWindowModality(Qt.WindowModal)
        self._scan_progress.show()

        self._scan_thread = QThread(self)
        self._scan_worker = ScanWorker(self.controller)
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.failed.connect(self._on_scan_failed)
        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_worker.failed.connect(self._scan_thread.quit)
        self._scan_thread.finished.connect(self._cleanup_scan)
        self._scan_thread.start()

    def _on_scan_finished(self, discovered_apps: object) -> None:
        results = discovered_apps if isinstance(discovered_apps, list) else []
        visible_results, ignored_count = filter_discovered_apps(results, list(self.manager_config.scan_ignore_rules))
        if not visible_results:
            if ignored_count:
                self.scan_status_label.setText(
                    f"Scan status: no visible results. {ignored_count} scan result(s) were hidden by ignore rules."
                )
                QMessageBox.information(
                    self,
                    "Scan Services",
                    f"No visible scan results remain. {ignored_count} result(s) were hidden by ignore rules.",
                )
            else:
                self.scan_status_label.setText("Scan status: no listening apps found.")
                QMessageBox.information(self, "Find Running Apps", "No listening apps found.")
            return

        hidden_suffix = f"; {ignored_count} hidden by ignore rules" if ignored_count else ""
        self.scan_status_label.setText(
            f"Scan status: found {len(visible_results)} visible listening service(s) or process(es){hidden_suffix}."
        )
        dialog = DiscoveryDialog(
            self.registry.config_dir,
            visible_results,
            self.controller.suggested_config,
            self._ignore_discovered_app,
            self,
        )
        if dialog.exec() != dialog.DialogCode.Accepted or dialog.selected_config is None:
            self.scan_status_label.setText(
                f"Scan status: found {len(visible_results)} visible result(s){hidden_suffix}; import canceled before saving a config."
            )
            return

        config = dialog.selected_config
        if self.registry.get(config.id) is not None:
            overwrite = QMessageBox.question(
                self,
                "Overwrite Config",
                f"A config with ID '{config.id}' already exists. Overwrite it?",
            )
            if overwrite != QMessageBox.StandardButton.Yes:
                self.scan_status_label.setText(
                    f"Scan status: found {len(visible_results)} visible result(s){hidden_suffix}; overwrite declined for '{config.id}'."
                )
                return

        path = self.registry.save(config)
        attach_message = ""
        if dialog.attach_current_process and dialog.selected_discovered_app is not None:
            attach_result = self.controller.attach_discovered_process(config, dialog.selected_discovered_app)
            attach_message = f"\nAttach result: {attach_result.message}"
            if not attach_result.ok:
                self._show_error("Attach Failed", attach_result.message)

        self.scan_status_label.setText(f"Scan status: saved imported config to {path.name}.{attach_message}")
        QMessageBox.information(
            self,
            "Config Saved",
            f"Saved config to {path}{attach_message}\nReview repo, entry target, and WinSW before starting it.",
        )
        self.reload_apps(show_errors=False)

    def _on_scan_failed(self, message: str) -> None:
        self.scan_status_label.setText(f"Scan status: failed - {message}")
        self._show_error("Scan Failed", message)

    def _cleanup_scan(self) -> None:
        if self._scan_progress is not None:
            self._scan_progress.close()
            self._scan_progress.deleteLater()
            self._scan_progress = None
        if self._scan_worker is not None:
            self._scan_worker.deleteLater()
            self._scan_worker = None
        if self._scan_thread is not None:
            self._scan_thread.deleteLater()
            self._scan_thread = None
        self.scan_button.setEnabled(True)
        self._finish_pending_close()

    def _save_and_reload_manager_config(self, manager_config: ManagerConfig) -> None:
        try:
            self.installation_manager.ensure_layout(manager_config)
            self.installation_manager.save(manager_config)
        except OSError as exc:
            self._show_error("Settings Error", str(exc))
            return

        self.manager_config = manager_config
        self.registry = AppRegistry(manager_config.apps_dir)
        self.controller = self._controller_factory(manager_config)
        self.scan_status_label.setText(f"Scan status: manager settings reloaded from {self.manager_config_path.name}.")
        self.reload_apps(show_errors=True)

    def _ignore_discovered_app(self, app) -> bool:
        rule = ScanIgnoreRule.from_discovered_app(app)
        if any(existing == rule for existing in self.manager_config.scan_ignore_rules):
            self.scan_status_label.setText(f"Scan status: ignore rule already exists for {rule.label}.")
            return True

        updated_config = ManagerConfig(
            apps_dir=self.manager_config.apps_dir,
            install_dir=self.manager_config.install_dir,
            runtime_dir=self.manager_config.runtime_dir,
            tools_dir=self.manager_config.tools_dir,
            logs_dir=self.manager_config.logs_dir,
            winsw_exe_path=self.manager_config.winsw_exe_path,
            scan_ignore_rules=(*self.manager_config.scan_ignore_rules, rule),
            initialized=self.manager_config.initialized,
        )
        try:
            self.installation_manager.save(updated_config)
        except OSError as exc:
            self._show_error("Ignore Failed", str(exc))
            return False

        self.manager_config = updated_config
        self.scan_status_label.setText(f"Scan status: added ignore rule for {rule.label}.")
        return True

    def _uninstall_managed_assets(self, manager_config: ManagerConfig) -> None:
        try:
            self.installation_manager.uninstall_managed_assets(manager_config)
            self.installation_manager.save(manager_config)
        except (OSError, ValueError) as exc:
            self._show_error("Uninstall Failed", str(exc))
            return

        QMessageBox.information(
            self,
            "Managed Assets Removed",
            "The managed python-webapp-manager root was removed. The app will close so setup can run again on next start.",
        )
        self.close()

    def _render_current_app(self, index: int) -> None:
        while self.detail_layout.rowCount():
            self.detail_layout.removeRow(0)

        context = self._context_for_row(index)
        if context is None:
            self.summary_label.setText("No app selected")
            self.app_url_label.setText("")
            self._reset_cards()
            self._sync_buttons(None, None)
            return

        config = context.config
        snapshot = context.snapshot
        management_state = self._management_state(config, snapshot)
        self.summary_label.setText(config.display_name)
        app_url = self._app_url(config)
        self.app_url_label.setText(f"{management_state} - <a href=\"{app_url}\">{app_url}</a>")
        uptime = _uptime_label(snapshot.runtime_started_at)
        _set_card(self.runtime_card, "Runtime", _runtime_label(snapshot), _status_color(snapshot.status))
        _set_card(self.health_card, "Health", snapshot.health, _health_color(snapshot.health))
        _set_card(self.git_card, "Git", _git_label(snapshot.git_state), _git_color(snapshot.git_state))
        _set_card(self.uptime_card, "Uptime", uptime, QColor("#e5e7eb"))
        self._sync_buttons(config, snapshot)

        details = {
            "Address": f"{config.host}:{config.port}",
            "Mode": f"{_mode_label(config.mode)} / active {_active_mode_label(snapshot.active_mode)}",
            "Repo": str(config.repo_path),
            "Branch": config.branch,
            "Entry": f"{config.entry_kind} {config.entry_target}",
            "Status detail": snapshot.status_detail,
            "Health detail": snapshot.health_detail,
            "Git": _git_label(snapshot.git_state),
            "Git detail": snapshot.git_detail,
        }
        if snapshot.last_action is not None:
            details["Last action"] = snapshot.last_action.name
        for label, value in details.items():
            self.detail_layout.addRow(_detail_label(label), _detail_value(value))

        self.stdout_view.set_log_path(config.log_dir / "stdout.log")
        self.stderr_view.set_log_path(config.log_dir / "stderr.log")

    def _selected_config(self) -> AppConfig | None:
        context = self._context_for_row(self.app_table.currentRow())
        if context is None:
            self._show_error("No Selection", "Select an app first.")
            return None
        return context.config

    def _show_result(self, ok: bool, message: str) -> None:
        if ok:
            QMessageBox.information(self, "App Manager", message)
        else:
            self._show_error("App Manager", message)

    def _show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)

    def _selected_app_id(self) -> str | None:
        context = self._context_for_row(self.app_table.currentRow())
        if context is None:
            return None
        return context.config.id

    def _poll_current_view(self) -> None:
        if not self.isVisible():
            return
        if self._action_thread is not None:
            return
        self.reload_apps(show_errors=False)
        self.stdout_view.refresh()
        self.stderr_view.refresh()

    def _run_selected_action(self, action_name: str, handler: Callable[[AppConfig], ActionResult]) -> None:
        if self._action_thread is not None:
            return
        config = self._selected_config()
        if not config:
            return

        self._action_progress = QProgressDialog(f"{action_name}...", "", 0, 0, self)
        self._action_progress.setWindowTitle(action_name)
        self._action_progress.setCancelButton(None)
        self._action_progress.setMinimumDuration(0)
        self._action_progress.setWindowModality(Qt.WindowModal)
        self._action_progress.show()
        self._sync_buttons(None, None)

        self._action_thread = QThread(self)
        self._action_worker = ActionWorker(action_name, config, handler)
        self._action_worker.moveToThread(self._action_thread)
        self._action_thread.started.connect(self._action_worker.run)
        self._action_worker.finished.connect(self._on_action_finished)
        self._action_worker.failed.connect(self._on_action_failed)
        self._action_worker.finished.connect(self._action_thread.quit)
        self._action_worker.failed.connect(self._action_thread.quit)
        self._action_thread.finished.connect(self._cleanup_action)
        self._action_thread.start()

    def _on_action_finished(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 2:
            self._on_action_failed("action returned an unexpected result")
            return
        action_name, result = payload
        if not isinstance(result, ActionResult):
            self._on_action_failed("action returned an unexpected result")
            return
        self._show_result(result.ok, result.message)
        self.scan_status_label.setText(f"{action_name}: {result.message}")
        self.reload_apps(show_errors=False)

    def _on_action_failed(self, message: str) -> None:
        self._show_error("App Manager", message)
        self.scan_status_label.setText(f"Action failed: {message}")
        self.reload_apps(show_errors=False)

    def _cleanup_action(self) -> None:
        if self._action_progress is not None:
            self._action_progress.close()
            self._action_progress.deleteLater()
            self._action_progress = None
        if self._action_worker is not None:
            self._action_worker.deleteLater()
            self._action_worker = None
        if self._action_thread is not None:
            self._action_thread.deleteLater()
            self._action_thread = None
        self._finish_pending_close()

    def _background_running(self) -> bool:
        return self._scan_thread is not None or self._refresh_thread is not None or self._action_thread is not None

    def _finish_pending_close(self) -> None:
        if self._close_requested and not self._background_running():
            self.close()

    def _sync_buttons(self, config: AppConfig | None, snapshot: AppSnapshot | None) -> None:
        if config is None or snapshot is None:
            for button in (
                self.start_button,
                self.stop_button,
                self.stop_external_button,
                self.restart_button,
                self.edit_app_button,
                self.open_app_button,
                self.install_service_button,
                self.uninstall_service_button,
                self.start_service_button,
                self.stop_service_button,
                self.restart_service_button,
                self.health_button,
                self.update_button,
                self.open_logs_button,
            ):
                button.setEnabled(False)
            self.add_app_button.setEnabled(True)
            self.edit_app_button.setEnabled(False)
            self.update_button.setText("Update App")
            self.update_button.setToolTip("")
            _set_button_role(self.update_button, "secondary")
            self.scan_button.setEnabled(self._scan_thread is None)
            self.settings_button.setEnabled(True)
            self.github_help_button.setEnabled(True)
            self.self_update_button.setEnabled(True)
            return

        dev_supported = config.mode in {"dev", "both"}
        prod_supported = config.mode in {"prod", "both"}
        observed = config.mode == "observed"
        external_active = snapshot.active_mode == "unknown" and "external pid" in snapshot.status_detail.lower()
        runtime_active = snapshot.active_mode in {"dev", "prod", "unknown"}

        self.add_app_button.setEnabled(True)
        self.edit_app_button.setEnabled(True)
        self.open_app_button.setEnabled(True)
        self.start_button.setEnabled(dev_supported and not runtime_active)
        self.stop_button.setEnabled(snapshot.active_mode == "dev")
        self.stop_external_button.setEnabled(not observed and external_active)
        self.restart_button.setEnabled(snapshot.active_mode == "dev")
        self.install_service_button.setEnabled(prod_supported)
        self.uninstall_service_button.setEnabled(prod_supported)
        self.start_service_button.setEnabled(prod_supported and not runtime_active)
        self.stop_service_button.setEnabled(snapshot.active_mode == "prod")
        self.restart_service_button.setEnabled(snapshot.active_mode == "prod")
        self.health_button.setEnabled(True)
        self.update_button.setEnabled(not observed)
        if snapshot.git_state == "update_available":
            self.update_button.setText("Update Available")
            self.update_button.setToolTip(snapshot.git_detail)
            _set_button_role(self.update_button, "warning")
        elif snapshot.git_state in {"dirty", "error"}:
            self.update_button.setText("Update App")
            self.update_button.setToolTip(snapshot.git_detail if snapshot.git_state != "unknown" else "")
            _set_button_role(self.update_button, "danger")
        else:
            self.update_button.setText("Update App")
            self.update_button.setToolTip(snapshot.git_detail if snapshot.git_state != "unknown" else "")
            _set_button_role(self.update_button, "secondary")
        self.open_logs_button.setEnabled(True)
        self.scan_button.setEnabled(self._scan_thread is None)
        self.settings_button.setEnabled(True)
        self.github_help_button.setEnabled(True)
        self.self_update_button.setEnabled(True)

    def _set_app_table_row(self, row: int, config: AppConfig, snapshot: AppSnapshot) -> None:
        values = [
            _traffic_light_label(snapshot),
            config.display_name,
            _runtime_label(snapshot),
            _git_label(snapshot.git_state),
        ]
        context = AppContext(config=config, snapshot=snapshot)
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 0:
                item.setTextAlignment(Qt.AlignCenter)
                _apply_item_status_style(item, _overall_color(snapshot), "overall status")
            if column == 1:
                item.setData(Qt.UserRole, context)
                item.setData(Qt.UserRole + 1, config.id)
                item.setToolTip(f"{config.host}:{config.port} - {snapshot.health}: {snapshot.health_detail}")
            if column == 2:
                _apply_item_status_style(item, _status_color(snapshot.status), snapshot.status_detail)
                item.setToolTip(snapshot.status_detail)
            if column == 3:
                _apply_item_status_style(item, _git_color(snapshot.git_state), snapshot.git_detail)
                item.setToolTip(snapshot.git_detail)
            self.app_table.setItem(row, column, item)

    def _context_for_row(self, row: int) -> AppContext | None:
        if row < 0:
            return None
        item = self.app_table.item(row, 0)
        if item is None:
            return None
        item = self.app_table.item(row, 1)
        if item is None:
            return None
        context = item.data(Qt.UserRole)
        if isinstance(context, AppContext):
            return context
        return None

    def _select_app_id(self, app_id: str) -> None:
        for row in range(self.app_table.rowCount()):
            item = self.app_table.item(row, 1)
            if item is not None and item.data(Qt.UserRole + 1) == app_id:
                self.app_table.selectRow(row)
                self._render_current_app(row)
                return
        if self.app_table.rowCount() > 0:
            self.app_table.selectRow(0)
            self._render_current_app(0)

    def _app_url(self, config: AppConfig) -> str:
        host = "127.0.0.1" if config.host in {"0.0.0.0", "::"} else config.host
        return f"http://{host}:{config.port}"

    def _management_state(self, config: AppConfig, snapshot: AppSnapshot) -> str:
        if config.mode == "observed":
            return "External"
        if (
            "attached" in snapshot.status_detail.lower()
            or snapshot.last_action is not None
            and snapshot.last_action.name == "attach_discovered_process"
        ):
            return "Attached"
        if config.mode in {"prod", "both"}:
            return "Service"
        return "Managed"

    def _reset_cards(self) -> None:
        _set_card(self.runtime_card, "Runtime", "-", QColor("#e5e7eb"))
        _set_card(self.health_card, "Health", "-", QColor("#e5e7eb"))
        _set_card(self.git_card, "Git", "-", QColor("#e5e7eb"))
        _set_card(self.uptime_card, "Uptime", "-", QColor("#e5e7eb"))


def _status_color(status: str) -> QColor:
    if status == "running":
        return QColor("#166534")
    if status in {"error", "unknown"}:
        return QColor("#991b1b")
    if status in {"starting", "stopping"}:
        return QColor("#a16207")
    return QColor("#4b5563")


def _health_color(health: str) -> QColor:
    if health == "healthy":
        return QColor("#166534")
    if health in {"unhealthy", "timeout", "error"}:
        return QColor("#991b1b")
    if health == "disabled":
        return QColor("#4b5563")
    return QColor("#a16207")


def _git_color(git_state: str) -> QColor:
    if git_state == "current":
        return QColor("#166534")
    if git_state == "update_available":
        return QColor("#a16207")
    if git_state in {"dirty", "error"}:
        return QColor("#991b1b")
    return QColor("#4b5563")


def _overall_color(snapshot: AppSnapshot) -> QColor:
    if snapshot.status == "running" and snapshot.health in {"healthy", "disabled"} and snapshot.git_state in {
        "current",
        "disabled",
    }:
        return QColor("#166534")
    if snapshot.status in {"error", "unknown"} or snapshot.health in {"unhealthy", "timeout", "error"}:
        return QColor("#991b1b")
    if snapshot.git_state in {"update_available", "dirty", "error"}:
        return QColor("#a16207")
    return QColor("#4b5563")


def _traffic_light_label(snapshot: AppSnapshot) -> str:
    color = _overall_color(snapshot).name()
    if color == "#166534":
        return "OK"
    if color == "#991b1b":
        return "ERR"
    if color == "#a16207":
        return "WARN"
    return "-"


def _git_label(git_state: str) -> str:
    labels = {
        "disabled": "-",
        "current": "current",
        "update_available": "update available",
        "dirty": "local changes",
        "error": "error",
        "unknown": "unknown",
    }
    return labels.get(git_state, "unknown")


def _runtime_label(snapshot: AppSnapshot) -> str:
    if snapshot.active_mode != "none":
        return f"{snapshot.status} / {_active_mode_label(snapshot.active_mode)}"
    return snapshot.status


def _mode_label(mode: str) -> str:
    labels = {
        "dev": "local process",
        "prod": "Windows service",
        "both": "local process or Windows service",
        "observed": "observed only",
    }
    return labels.get(mode, mode)


def _active_mode_label(active_mode: str) -> str:
    labels = {
        "dev": "local process",
        "prod": "Windows service",
        "unknown": "external listener",
        "none": "none",
    }
    return labels.get(active_mode, active_mode)


def _uptime_label(started_at: str | None) -> str:
    if not started_at:
        return "-"
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except ValueError:
        return "-"
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    seconds = max(0, int((datetime.now(timezone.utc) - started.astimezone(timezone.utc)).total_seconds()))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _seconds = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _status_card(title: str, value: str) -> QLabel:
    label = QLabel()
    label.setObjectName("statusCard")
    label.setFrameShape(QFrame.StyledPanel)
    label.setMinimumHeight(62)
    label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    label.setWordWrap(True)
    _set_card(label, title, value, QColor("#e5e7eb"))
    return label


def _set_card(label: QLabel, title: str, value: str, color: QColor) -> None:
    label.setText(f"{title}\n{value}")
    label.setStyleSheet(
        "QLabel {"
        "background-color: #202428;"
        "color: #f4f7fb;"
        "border: 1px solid #333a42;"
        f"border-left: 4px solid {color.name()};"
        "border-radius: 5px;"
        "padding: 8px 10px;"
        "font-weight: 600;"
        "}"
    )


def _apply_item_status_style(item: QTableWidgetItem, color: QColor, tooltip: str) -> None:
    item.setBackground(_soft_status_color(color))
    item.setForeground(QColor("#f6f8fb"))
    item.setToolTip(tooltip)


def _soft_status_color(color: QColor) -> QColor:
    name = color.name().lower()
    if name == "#166534":
        return QColor("#17442a")
    if name == "#991b1b":
        return QColor("#541d20")
    if name == "#a16207":
        return QColor("#4f3716")
    return QColor("#2d333b")


def _detail_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("detailKey")
    return label


def _detail_value(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("detailValue")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


def _set_button_role(button: QPushButton, role: str) -> None:
    button.setProperty("role", role)
    button.setMinimumHeight(30)
    button.style().unpolish(button)
    button.style().polish(button)


def _show_github_help(parent: QWidget) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle("GitHub and update checks")
    dialog.resize(760, 620)
    apply_dialog_style(dialog)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(14, 14, 14, 14)
    layout.setSpacing(10)

    content = QTextBrowser()
    content.setObjectName("helpBrowser")
    content.setOpenExternalLinks(True)
    content.setHtml(
        """
        <h1>How App Manager checks GitHub updates</h1>
        <p>
          App Manager does not compare against a random folder on GitHub.
          Each connected app needs a <b>local Git clone on this machine</b>.
          The app then asks Git to compare that local clone with its remote branch,
          usually <code>origin/main</code>.
        </p>

        <h2>Normal setup</h2>
        <ol>
          <li>Clone the web app repository on the server or workstation that runs App Manager.</li>
          <li>Use that clone as <code>repo_path</code> when connecting the app.</li>
          <li>Set <code>branch</code> to the deployed branch, for example <code>main</code>.</li>
          <li>Confirm that <code>git fetch origin main --prune</code> works in that folder.</li>
        </ol>

        <pre>cd C:\\Python\\your_web_app
git remote -v
git fetch origin main --prune
git status</pre>

        <h2>What Refresh does</h2>
        <p>
          Refresh runs <code>git fetch origin &lt;branch&gt; --prune</code> and then compares
          <code>HEAD</code> with <code>origin/&lt;branch&gt;</code>.
          If the local install is behind the remote branch, App Manager shows
          <b>update available</b>.
        </p>

        <h2>What Update does</h2>
        <p>
          Update checks that the path is a Git working tree. Local changes do not block the update;
          Git temporarily stashes them with <code>--autostash</code> and applies them again after the pull.
        </p>
        <pre>git fetch --all --prune
git checkout &lt;branch&gt;
git pull --ff-only --autostash origin &lt;branch&gt;</pre>
        <p>
          After that it installs <code>requirements.txt</code> if configured or present,
          and runs the optional init command if one is configured. If Git reports a conflict,
          resolve it in the app repository and run Update again.
        </p>

        <h2>Private GitHub repositories</h2>
        <p>
          Private repositories work as long as Git can fetch them outside App Manager.
          The recommended options are GitHub Desktop, Git Credential Manager, or the GitHub CLI:
        </p>
        <pre>gh auth login
gh repo clone OWNER/PRIVATE_REPO C:\\Python\\your_web_app</pre>
        <p>
          App Manager does not need your GitHub password or token. It uses the credentials
          already configured for the Windows user running the app.
        </p>

        <h2>Server note</h2>
        <p>
          If App Manager is later run under a Windows service account, GitHub access must also
          work for that same account. A clone that works for your interactive user may not work
          for a different service user until credentials or SSH keys are configured there too.
        </p>
        """
    )
    layout.addWidget(content)

    buttons = QDialogButtonBox(QDialogButtonBox.Close)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.exec()


def _apply_app_style(window: QWidget) -> None:
    window.setStyleSheet(
        """
        QMainWindow {
            background: #151719;
            color: #eef2f6;
        }
        QSplitter::handle {
            background: #2c3238;
            width: 1px;
        }
        QScrollArea {
            background: #151719;
            border: 0;
        }
        QScrollArea > QWidget > QWidget {
            background: #151719;
        }
        QTableWidget {
            background: #1d2023;
            alternate-background-color: #23272b;
            color: #eef2f6;
            border: 0;
            gridline-color: #343a41;
            selection-background-color: #31516b;
            selection-color: #ffffff;
        }
        QHeaderView::section {
            background: #262b30;
            color: #dce4ed;
            border: 0;
            border-bottom: 1px solid #3a424a;
            padding: 7px 8px;
            font-weight: 600;
        }
        QLabel#appTitle {
            color: #f7fafc;
            font-size: 18px;
            font-weight: 700;
        }
        QLabel#appUrl {
            color: #94a3b8;
        }
        QLabel#appUrl a {
            color: #7dd3fc;
            text-decoration: none;
        }
        QLabel#statusLine {
            color: #aeb8c4;
            padding: 2px 0;
        }
        QGroupBox#surface {
            background: #1b1e21;
            border: 1px solid #353c44;
            border-radius: 6px;
            margin-top: 9px;
            color: #f1f5f9;
            font-weight: 600;
        }
        QGroupBox#surface::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 6px;
            color: #cbd5e1;
        }
        QLabel#detailKey {
            color: #96a3b2;
            font-weight: 600;
        }
        QLabel#detailValue {
            color: #edf2f7;
        }
        QPushButton {
            background: #252a2f;
            color: #eef2f6;
            border: 1px solid #3a424a;
            border-radius: 5px;
            padding: 6px 10px;
            font-weight: 600;
        }
        QPushButton:hover {
            background: #303740;
            border-color: #4b5563;
        }
        QPushButton:disabled {
            color: #717c89;
            background: #202326;
            border-color: #30363d;
        }
        QPushButton[role="primary"] {
            background: #1f6f4a;
            border-color: #2d8a5d;
        }
        QPushButton[role="primary"]:hover {
            background: #277f57;
        }
        QPushButton[role="danger"] {
            background: #6f2429;
            border-color: #93343a;
        }
        QPushButton[role="danger"]:hover {
            background: #823038;
        }
        QPushButton[role="warning"] {
            background: #76551c;
            border-color: #9a722b;
        }
        QPushButton[role="warning"]:hover {
            background: #876323;
        }
        QTabWidget::pane {
            border: 1px solid #353c44;
            border-radius: 5px;
            top: -1px;
        }
        QTabBar::tab {
            background: #23272c;
            color: #cbd5e1;
            border: 1px solid #353c44;
            padding: 6px 14px;
            margin-right: 2px;
        }
        QTabBar::tab:selected {
            background: #303740;
            color: #ffffff;
        }
        QTextEdit {
            background: #111315;
            color: #e5edf5;
            border: 0;
            font-family: Consolas, "Cascadia Mono", monospace;
            font-size: 11px;
            selection-background-color: #31516b;
        }
        QTextBrowser#helpBrowser {
            background: #151719;
            color: #e8eef5;
            border: 1px solid #353c44;
            border-radius: 6px;
            padding: 12px;
            font-size: 13px;
        }
        QTextBrowser#helpBrowser h1 {
            color: #ffffff;
            font-size: 22px;
        }
        QTextBrowser#helpBrowser h2 {
            color: #dbeafe;
            font-size: 16px;
        }
        QTextBrowser#helpBrowser code,
        QTextBrowser#helpBrowser pre {
            background: #0f1113;
            color: #d7e3ef;
            font-family: Consolas, "Cascadia Mono", monospace;
        }
        QScrollBar:vertical {
            background: #111315;
            width: 12px;
            margin: 0;
            border-left: 1px solid #353c44;
        }
        QScrollBar::handle:vertical {
            background: #3a424a;
            min-height: 24px;
            border-radius: 5px;
        }
        QScrollBar::handle:vertical:hover {
            background: #4b5563;
        }
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {
            height: 0;
        }
        QScrollBar:horizontal {
            background: #111315;
            height: 12px;
            margin: 0;
            border-top: 1px solid #353c44;
        }
        QScrollBar::handle:horizontal {
            background: #3a424a;
            min-width: 24px;
            border-radius: 5px;
        }
        QScrollBar::handle:horizontal:hover {
            background: #4b5563;
        }
        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal {
            width: 0;
        }
        """
    )
