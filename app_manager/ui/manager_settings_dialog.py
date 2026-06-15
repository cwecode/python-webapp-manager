from __future__ import annotations

import platform
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app_manager.core.winsw import WinSWDetector, download_winsw
from app_manager.models import ConfigValidationError, ManagerConfig
from app_manager.models.manager import recommended_winsw_filename


class WinSWDetectWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, detector: WinSWDetector, install_dir: Path) -> None:
        super().__init__()
        self.detector = detector
        self.install_dir = install_dir

    def run(self) -> None:
        try:
            self.finished.emit(self.detector.discover(self.install_dir))
        except Exception as exc:
            self.failed.emit(str(exc))


class WinSWDownloadWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, target_path: Path) -> None:
        super().__init__()
        self.target_path = target_path

    def run(self) -> None:
        try:
            self.finished.emit(download_winsw(self.target_path))
        except Exception as exc:
            self.failed.emit(str(exc))


class ManagerSettingsDialog(QDialog):
    def __init__(
        self,
        manager_config: ManagerConfig,
        *,
        base_dir: Path,
        setup_mode: bool,
        allow_uninstall: bool,
        winsw_detector: WinSWDetector | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._base_dir = base_dir
        self._selected_config: ManagerConfig | None = None
        self._request_uninstall = False
        self._winsw_detector = winsw_detector or WinSWDetector()
        self._base_config = manager_config
        self._detect_thread: QThread | None = None
        self._detect_worker: WinSWDetectWorker | None = None
        self._download_thread: QThread | None = None
        self._download_worker: WinSWDownloadWorker | None = None
        self._detected_winsw_paths: list[Path] = []
        self._close_requested = False
        self._reject_requested = False

        self.setWindowTitle("Initial Setup" if setup_mode else "Settings")
        self.resize(840, 420)

        root_layout = QVBoxLayout(self)
        intro = QLabel("Choose one manager root. App configs, runtime files, tools, and logs stay below it.")
        intro.setWordWrap(True)
        root_layout.addWidget(intro)

        platform_hint = QLabel(f"Machine: {platform.machine() or 'unknown'} | WinSW: {recommended_winsw_filename()}")
        platform_hint.setWordWrap(True)
        root_layout.addWidget(platform_hint)

        root_label = QLabel("Manager root")
        root_layout.addWidget(root_label)
        self.install_dir_input = QLineEdit(str(manager_config.install_dir))
        self.install_dir_input.textChanged.connect(self._refresh_structure_preview)
        self.install_dir_input.editingFinished.connect(self._start_winsw_detection)
        root_layout.addWidget(self._path_row(self.install_dir_input, self._browse_install_dir))

        self.structure_preview = QLabel()
        self.structure_preview.setWordWrap(True)
        root_layout.addWidget(self.structure_preview)

        winsw_title = QLabel("WinSW")
        root_layout.addWidget(winsw_title)

        self.winsw_status_label = QLabel("Checking for WinSW...")
        self.winsw_status_label.setWordWrap(True)
        root_layout.addWidget(self.winsw_status_label)

        self.winsw_progress = QProgressBar()
        self.winsw_progress.setRange(0, 0)
        root_layout.addWidget(self.winsw_progress)

        winsw_actions = QWidget()
        winsw_actions_layout = QHBoxLayout(winsw_actions)
        winsw_actions_layout.setContentsMargins(0, 0, 0, 0)
        self.search_again_button = QPushButton("Search Again")
        self.search_again_button.clicked.connect(self._start_winsw_detection)
        winsw_actions_layout.addWidget(self.search_again_button)
        self.use_detected_button = QPushButton("Use Detected WinSW")
        self.use_detected_button.clicked.connect(self._use_detected_winsw)
        self.use_detected_button.setEnabled(False)
        winsw_actions_layout.addWidget(self.use_detected_button)
        self.download_winsw_button = QPushButton("Download WinSW")
        self.download_winsw_button.clicked.connect(self._start_winsw_download)
        winsw_actions_layout.addWidget(self.download_winsw_button)
        winsw_actions_layout.addStretch(1)
        root_layout.addWidget(winsw_actions)

        self.use_existing_winsw_checkbox = QCheckBox("Use an existing WinSW executable")
        self.use_existing_winsw_checkbox.toggled.connect(self._toggle_existing_winsw)
        root_layout.addWidget(self.use_existing_winsw_checkbox)

        self.existing_winsw_input = QLineEdit(str(manager_config.winsw_exe_path))
        self.existing_winsw_row = self._path_row(self.existing_winsw_input, self._browse_winsw_file)
        root_layout.addWidget(self.existing_winsw_row)

        self.effective_winsw_label = QLabel()
        self.effective_winsw_label.setWordWrap(True)
        root_layout.addWidget(self.effective_winsw_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        save_button = buttons.addButton("Save and Continue" if setup_mode else "Save and Reload", QDialogButtonBox.AcceptRole)
        save_button.clicked.connect(self._save)
        buttons.rejected.connect(self.reject)

        if allow_uninstall:
            uninstall_button = QPushButton("Uninstall Managed Assets")
            uninstall_button.clicked.connect(self._uninstall)
            buttons.addButton(uninstall_button, QDialogButtonBox.DestructiveRole)

        root_layout.addWidget(buttons)

        default_winsw_path = str(manager_config.tools_dir / recommended_winsw_filename())
        self.use_existing_winsw_checkbox.setChecked(str(manager_config.winsw_exe_path) != default_winsw_path)
        self._refresh_structure_preview()
        self._toggle_existing_winsw(self.use_existing_winsw_checkbox.isChecked())
        self._start_winsw_detection()

    @property
    def selected_config(self) -> ManagerConfig | None:
        return self._selected_config

    @property
    def request_uninstall(self) -> bool:
        return self._request_uninstall

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._background_running():
            self._close_requested = True
            self._reject_requested = False
            self.setEnabled(False)
            self.winsw_status_label.setText("Waiting for the current WinSW background task to finish before closing...")
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self) -> None:  # type: ignore[override]
        if self._background_running():
            self._reject_requested = True
            self._close_requested = False
            self.setEnabled(False)
            self.winsw_status_label.setText("Waiting for the current WinSW background task to finish before closing...")
            return
        super().reject()

    def _save(self) -> None:
        try:
            self._selected_config = self._build_config(initialized=True)
        except ConfigValidationError as exc:
            QMessageBox.critical(self, "Invalid Settings", "\n".join(exc.errors))
            return
        self._request_uninstall = False
        self.accept()

    def _uninstall(self) -> None:
        try:
            self._selected_config = self._build_config(initialized=False)
        except ConfigValidationError as exc:
            QMessageBox.critical(self, "Invalid Settings", "\n".join(exc.errors))
            return
        confirm = QMessageBox.question(
            self,
            "Uninstall Managed Assets",
            "This removes the managed python-webapp-manager root directory. Continue?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._request_uninstall = True
        self.accept()

    def _build_config(self, initialized: bool) -> ManagerConfig:
        install_dir = self.install_dir_input.text().strip()
        install_root = Path(install_dir) if install_dir else Path()
        winsw_path = (
            self.existing_winsw_input.text().strip()
            if self.use_existing_winsw_checkbox.isChecked()
            else str(install_root / "tools" / recommended_winsw_filename())
        )
        payload = {
            "apps_dir": str(install_root / "apps") if install_dir else "",
            "install_dir": install_dir,
            "runtime_dir": str(install_root / "runtime") if install_dir else "",
            "tools_dir": str(install_root / "tools") if install_dir else "",
            "logs_dir": str(install_root / "logs") if install_dir else "",
            "winsw_exe_path": winsw_path,
            "scan_ignore_rules": [rule.to_dict(self._base_dir) for rule in self._base_config.scan_ignore_rules],
            "initialized": initialized,
        }
        return ManagerConfig.from_dict(payload, self._base_dir)

    def _path_row(self, line_edit: QLineEdit, browse_handler: object) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(line_edit, 1)
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(browse_handler)  # type: ignore[arg-type]
        layout.addWidget(browse_button)
        return row

    def _browse_install_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select Install Directory", self.install_dir_input.text())
        if selected:
            self.install_dir_input.setText(selected)
            self._start_winsw_detection()

    def _browse_winsw_file(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select WinSW Executable",
            self.existing_winsw_input.text(),
            "Executable (*.exe)",
        )
        if selected:
            self.existing_winsw_input.setText(selected)
            self.use_existing_winsw_checkbox.setChecked(True)
            self._refresh_structure_preview()

    def _refresh_structure_preview(self) -> None:
        install_dir = Path(self.install_dir_input.text().strip() or ".")
        self.structure_preview.setText(
            "Folders:\n"
            f"{install_dir}\\apps\n"
            f"{install_dir}\\runtime\n"
            f"{install_dir}\\tools\n"
            f"{install_dir}\\logs"
        )
        managed_winsw_path = install_dir / "tools" / recommended_winsw_filename()
        effective_path = (
            self.existing_winsw_input.text().strip()
            if self.use_existing_winsw_checkbox.isChecked()
            else str(managed_winsw_path)
        )
        self.effective_winsw_label.setText(f"Effective WinSW path: {effective_path}")

    def _toggle_existing_winsw(self, checked: bool) -> None:
        self.existing_winsw_row.setEnabled(checked)
        self._refresh_structure_preview()

    def _start_winsw_detection(self) -> None:
        if self._detect_thread is not None or self._download_thread is not None:
            return

        self.winsw_status_label.setText("Checking for an existing WinSW installation...")
        self.winsw_progress.setVisible(True)
        self.search_again_button.setEnabled(False)
        self.download_winsw_button.setEnabled(False)
        self.use_detected_button.setEnabled(False)
        self._detected_winsw_paths = []

        self._detect_thread = QThread(self)
        self._detect_worker = WinSWDetectWorker(self._winsw_detector, Path(self.install_dir_input.text().strip() or "."))
        self._detect_worker.moveToThread(self._detect_thread)
        self._detect_thread.started.connect(self._detect_worker.run)
        self._detect_worker.finished.connect(self._on_winsw_detected)
        self._detect_worker.failed.connect(self._on_winsw_detection_failed)
        self._detect_worker.finished.connect(self._detect_thread.quit)
        self._detect_worker.failed.connect(self._detect_thread.quit)
        self._detect_thread.finished.connect(self._cleanup_detection)
        self._detect_thread.start()

    def _on_winsw_detected(self, paths: object) -> None:
        self._detected_winsw_paths = [path for path in paths if isinstance(path, Path)] if isinstance(paths, list) else []
        if not self._detected_winsw_paths:
            self.winsw_status_label.setText(
            "No WinSW found. Use the managed default, download it, or browse to an existing .exe."
            )
            return

        first_path = self._detected_winsw_paths[0]
        self.winsw_status_label.setText(
            f"Found {len(self._detected_winsw_paths)} WinSW candidate(s). Suggested: {first_path}"
        )
        self.use_detected_button.setEnabled(True)

    def _on_winsw_detection_failed(self, message: str) -> None:
        self.winsw_status_label.setText(
            f"WinSW search failed: {message}. You can still use the managed default or browse manually."
        )

    def _cleanup_detection(self) -> None:
        self.winsw_progress.setVisible(False)
        self.search_again_button.setEnabled(True)
        self.download_winsw_button.setEnabled(True)
        if self._detect_worker is not None:
            self._detect_worker.deleteLater()
            self._detect_worker = None
        if self._detect_thread is not None:
            self._detect_thread.deleteLater()
            self._detect_thread = None
        self._finish_pending_close()

    def _use_detected_winsw(self) -> None:
        if not self._detected_winsw_paths:
            return
        self.existing_winsw_input.setText(str(self._detected_winsw_paths[0]))
        self.use_existing_winsw_checkbox.setChecked(True)
        self._refresh_structure_preview()

    def _start_winsw_download(self) -> None:
        if self._download_thread is not None or self._detect_thread is not None:
            return

        target_path = Path(self.install_dir_input.text().strip() or ".") / "tools" / recommended_winsw_filename()
        self.winsw_status_label.setText(f"Downloading WinSW to {target_path}...")
        self.winsw_progress.setVisible(True)
        self.search_again_button.setEnabled(False)
        self.download_winsw_button.setEnabled(False)
        self.use_detected_button.setEnabled(False)

        self._download_thread = QThread(self)
        self._download_worker = WinSWDownloadWorker(target_path)
        self._download_worker.moveToThread(self._download_thread)
        self._download_thread.started.connect(self._download_worker.run)
        self._download_worker.finished.connect(self._on_winsw_downloaded)
        self._download_worker.failed.connect(self._on_winsw_download_failed)
        self._download_worker.finished.connect(self._download_thread.quit)
        self._download_worker.failed.connect(self._download_thread.quit)
        self._download_thread.finished.connect(self._cleanup_download)
        self._download_thread.start()

    def _on_winsw_downloaded(self, path: object) -> None:
        if not isinstance(path, Path):
            self.winsw_status_label.setText("WinSW download finished, but returned no usable path.")
            return
        self.use_existing_winsw_checkbox.setChecked(False)
        self.existing_winsw_input.setText(str(path))
        self.winsw_status_label.setText(f"Downloaded managed WinSW: {path}")
        self._refresh_structure_preview()

    def _on_winsw_download_failed(self, message: str) -> None:
        self.winsw_status_label.setText(
            f"WinSW download failed: {message}. Retry, browse manually, or continue without service actions."
        )

    def _cleanup_download(self) -> None:
        self.winsw_progress.setVisible(False)
        self.search_again_button.setEnabled(True)
        self.download_winsw_button.setEnabled(True)
        if self._download_worker is not None:
            self._download_worker.deleteLater()
            self._download_worker = None
        if self._download_thread is not None:
            self._download_thread.deleteLater()
            self._download_thread = None
        self._finish_pending_close()

    def _background_running(self) -> bool:
        return self._detect_thread is not None or self._download_thread is not None

    def _finish_pending_close(self) -> None:
        if self._background_running():
            return
        if self._reject_requested:
            self._reject_requested = False
            super().reject()
            return
        if self._close_requested:
            self._close_requested = False
            self.close()
