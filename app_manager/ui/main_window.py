from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app_manager.core.installation import InstallationManager
from app_manager.core.controller import AppController
from app_manager.core.registry import AppRegistry
from app_manager.models import AppConfig, AppSnapshot, ConfigValidationError, ManagerConfig, ScanIgnoreRule, filter_discovered_apps
from app_manager.ui.discovery_dialog import DiscoveryDialog
from app_manager.ui.log_viewer import LogViewer
from app_manager.ui.manager_settings_dialog import ManagerSettingsDialog


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

        self.setWindowTitle("App Manager")
        self.resize(1200, 720)

        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        self.app_list = QListWidget()
        self.app_list.currentRowChanged.connect(self._render_current_app)
        splitter.addWidget(self.app_list)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        splitter.addWidget(right_panel)

        self.summary_label = QLabel("No app selected")
        self.summary_label.setWordWrap(True)
        right_layout.addWidget(self.summary_label)

        detail_widget = QWidget()
        self.detail_layout = QFormLayout(detail_widget)
        right_layout.addWidget(detail_widget)

        action_grid = QGridLayout()
        right_layout.addLayout(action_grid)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(lambda: self.reload_apps(show_errors=True))
        action_grid.addWidget(self.refresh_button, 0, 0)

        self.start_button = QPushButton("Start Dev")
        self.start_button.clicked.connect(self.start_dev)
        action_grid.addWidget(self.start_button, 0, 1)

        self.stop_button = QPushButton("Stop Dev")
        self.stop_button.clicked.connect(self.stop_dev)
        action_grid.addWidget(self.stop_button, 0, 2)

        self.restart_button = QPushButton("Restart Dev")
        self.restart_button.clicked.connect(self.restart_dev)
        action_grid.addWidget(self.restart_button, 0, 3)

        self.install_service_button = QPushButton("Install Service")
        self.install_service_button.clicked.connect(self.install_service)
        action_grid.addWidget(self.install_service_button, 1, 0)

        self.uninstall_service_button = QPushButton("Uninstall Service")
        self.uninstall_service_button.clicked.connect(self.uninstall_service)
        action_grid.addWidget(self.uninstall_service_button, 1, 1)

        self.start_service_button = QPushButton("Start Service")
        self.start_service_button.clicked.connect(self.start_service)
        action_grid.addWidget(self.start_service_button, 1, 2)

        self.stop_service_button = QPushButton("Stop Service")
        self.stop_service_button.clicked.connect(self.stop_service)
        action_grid.addWidget(self.stop_service_button, 1, 3)

        self.restart_service_button = QPushButton("Restart Service")
        self.restart_service_button.clicked.connect(self.restart_service)
        action_grid.addWidget(self.restart_service_button, 1, 4)

        self.health_button = QPushButton("Check Health")
        self.health_button.clicked.connect(self.check_health)
        action_grid.addWidget(self.health_button, 2, 0)

        self.update_button = QPushButton("Update")
        self.update_button.clicked.connect(self.update_app)
        action_grid.addWidget(self.update_button, 2, 1)

        self.open_logs_button = QPushButton("Open Logs")
        self.open_logs_button.clicked.connect(self.open_logs)
        action_grid.addWidget(self.open_logs_button, 2, 2)

        self.scan_button = QPushButton("Scan Services")
        self.scan_button.clicked.connect(self.scan_services)
        action_grid.addWidget(self.scan_button, 2, 3)

        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self.open_settings)
        action_grid.addWidget(self.settings_button, 2, 4)

        self.scan_status_label = QLabel("Scan status: not started")
        self.scan_status_label.setWordWrap(True)
        right_layout.addWidget(self.scan_status_label)

        logs_row = QHBoxLayout()
        right_layout.addLayout(logs_row)

        stdout_panel = QWidget()
        stdout_layout = QVBoxLayout(stdout_panel)
        stdout_layout.addWidget(QLabel("stdout.log"))
        self.stdout_view = LogViewer()
        stdout_layout.addWidget(self.stdout_view)

        stderr_panel = QWidget()
        stderr_layout = QVBoxLayout(stderr_panel)
        stderr_layout.addWidget(QLabel("stderr.log"))
        self.stderr_view = LogViewer()
        stderr_layout.addWidget(self.stderr_view)

        logs_row.addWidget(stdout_panel)
        logs_row.addWidget(stderr_panel)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(2000)
        self._poll_timer.timeout.connect(self._poll_current_view)
        self._poll_timer.start()

        self.reload_apps(show_errors=True)

    def reload_apps(self, show_errors: bool) -> None:
        selected_app_id = self._selected_app_id()
        self.app_list.clear()
        self._snapshots = {}
        try:
            self._apps = self.registry.load_all()
        except ConfigValidationError as exc:
            self._apps = []
            if show_errors:
                self._show_error("Configuration Error", "\n".join(exc.errors))
            return

        selected_index = 0
        for index, config in enumerate(self._apps):
            snapshot = self.controller.snapshot(config)
            self._snapshots[config.id] = snapshot
            item = QListWidgetItem(self._item_text(config, snapshot))
            item.setData(Qt.UserRole, AppContext(config=config, snapshot=snapshot))
            self.app_list.addItem(item)
            if config.id == selected_app_id:
                selected_index = index

        if self._apps:
            self.app_list.setCurrentRow(selected_index)
        else:
            self.summary_label.setText(f"No apps configured in {self.registry.config_dir}")
            self.stdout_view.set_log_path(None)
            self.stderr_view.set_log_path(None)

    def start_dev(self) -> None:
        config = self._selected_config()
        if not config:
            return
        result = self.controller.start_dev(config)
        self._show_result(result.ok, result.message)
        self.reload_apps(show_errors=False)

    def stop_dev(self) -> None:
        config = self._selected_config()
        if not config:
            return
        result = self.controller.stop_dev(config)
        self._show_result(result.ok, result.message)
        self.reload_apps(show_errors=False)

    def restart_dev(self) -> None:
        config = self._selected_config()
        if not config:
            return
        result = self.controller.restart_dev(config)
        self._show_result(result.ok, result.message)
        self.reload_apps(show_errors=False)

    def check_health(self) -> None:
        config = self._selected_config()
        if not config:
            return
        result = self.controller.check_health(config)
        self._show_result(result.ok, result.message)
        self.reload_apps(show_errors=False)

    def update_app(self) -> None:
        config = self._selected_config()
        if not config:
            return
        result = self.controller.update_app(config)
        self._show_result(result.ok, result.message)
        self.reload_apps(show_errors=False)

    def install_service(self) -> None:
        config = self._selected_config()
        if not config:
            return
        result = self.controller.install_service(config)
        self._show_result(result.ok, result.message)
        self.reload_apps(show_errors=False)

    def uninstall_service(self) -> None:
        config = self._selected_config()
        if not config:
            return
        result = self.controller.uninstall_service(config)
        self._show_result(result.ok, result.message)
        self.reload_apps(show_errors=False)

    def start_service(self) -> None:
        config = self._selected_config()
        if not config:
            return
        result = self.controller.start_service(config)
        self._show_result(result.ok, result.message)
        self.reload_apps(show_errors=False)

    def stop_service(self) -> None:
        config = self._selected_config()
        if not config:
            return
        result = self.controller.stop_service(config)
        self._show_result(result.ok, result.message)
        self.reload_apps(show_errors=False)

    def restart_service(self) -> None:
        config = self._selected_config()
        if not config:
            return
        result = self.controller.restart_service(config)
        self._show_result(result.ok, result.message)
        self.reload_apps(show_errors=False)

    def open_logs(self) -> None:
        config = self._selected_config()
        if not config:
            return
        result = self.controller.open_logs(config)
        self._show_result(result.ok, result.message)
        self.reload_apps(show_errors=False)

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

    def scan_services(self) -> None:
        if self._scan_thread is not None:
            return

        self.scan_button.setEnabled(False)
        self.scan_status_label.setText("Scan status: scanning local services and listening ports...")
        self._scan_progress = QProgressDialog("Scanning local services...", "", 0, 0, self)
        self._scan_progress.setWindowTitle("Scan Services")
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
                self.scan_status_label.setText("Scan status: no listening services or processes were detected.")
                QMessageBox.information(self, "Scan Services", "No listening services or processes were detected.")
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
        self.scan_status_label.setText(f"Scan status: saved imported config to {path.name}.")
        QMessageBox.information(
            self,
            "Config Saved",
            f"Saved config to {path}\nReview repo, entry target, and WinSW values before managing the app.",
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

        if index < 0 or index >= len(self._apps):
            self._sync_buttons(None, None)
            return

        config = self._apps[index]
        snapshot = self._snapshots[config.id]
        self.summary_label.setText(
            f"{config.display_name} | mode={config.mode} | active={snapshot.active_mode} "
            f"| status={snapshot.status} | health={snapshot.health}"
        )
        self._sync_buttons(config, snapshot)

        details = {
            "ID": config.id,
            "Mode": config.mode,
            "Repo": str(config.repo_path),
            "Python": str(config.python_path),
            "Venv": str(config.venv_path),
            "Branch": config.branch,
            "Entry": f"{config.entry_kind} {config.entry_target}",
            "Bind": f"{config.host}:{config.port}",
            "Service": config.service_name,
            "Runtime": snapshot.active_mode,
            "Status detail": snapshot.status_detail,
            "Health detail": snapshot.health_detail,
            "Log dir": str(config.log_dir),
            "WinSW": str(config.winsw_exe_path),
        }
        if snapshot.last_action is not None:
            details["Last action"] = snapshot.last_action.name
            details["Last action time"] = snapshot.last_action.timestamp
            details["Last action detail"] = snapshot.last_action.message
        for label, value in details.items():
            self.detail_layout.addRow(QLabel(label), QLabel(value))

        self.stdout_view.set_log_path(config.log_dir / "stdout.log")
        self.stderr_view.set_log_path(config.log_dir / "stderr.log")

    def _selected_config(self) -> AppConfig | None:
        item = self.app_list.currentItem()
        if item is None:
            self._show_error("No Selection", "Select an app first.")
            return None
        context = item.data(Qt.UserRole)
        if context is None:
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
        item = self.app_list.currentItem()
        if item is None:
            return None
        context = item.data(Qt.UserRole)
        if context is None:
            return None
        return context.config.id

    def _poll_current_view(self) -> None:
        if not self.isVisible():
            return
        self.reload_apps(show_errors=False)
        self.stdout_view.refresh()
        self.stderr_view.refresh()

    def _sync_buttons(self, config: AppConfig | None, snapshot: AppSnapshot | None) -> None:
        if config is None or snapshot is None:
            for button in (
                self.start_button,
                self.stop_button,
                self.restart_button,
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
            self.scan_button.setEnabled(self._scan_thread is None)
            self.settings_button.setEnabled(True)
            return

        dev_supported = config.mode in {"dev", "both"}
        prod_supported = config.mode in {"prod", "both"}
        runtime_active = snapshot.active_mode in {"dev", "prod"}

        self.start_button.setEnabled(dev_supported and not runtime_active)
        self.stop_button.setEnabled(snapshot.active_mode == "dev")
        self.restart_button.setEnabled(snapshot.active_mode == "dev")
        self.install_service_button.setEnabled(prod_supported)
        self.uninstall_service_button.setEnabled(prod_supported)
        self.start_service_button.setEnabled(prod_supported and not runtime_active)
        self.stop_service_button.setEnabled(snapshot.active_mode == "prod")
        self.restart_service_button.setEnabled(snapshot.active_mode == "prod")
        self.health_button.setEnabled(True)
        self.update_button.setEnabled(True)
        self.open_logs_button.setEnabled(True)
        self.scan_button.setEnabled(self._scan_thread is None)
        self.settings_button.setEnabled(True)

    def _item_text(self, config: AppConfig, snapshot: AppSnapshot) -> str:
        last_action = snapshot.last_action.name if snapshot.last_action else "-"
        return (
            f"{config.display_name} ({config.mode}) | port={config.port} | "
            f"status={snapshot.status} | health={snapshot.health} | last={last_action}"
        )
