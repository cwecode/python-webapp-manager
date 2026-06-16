from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWizard,
    QWizardPage,
    QWidget,
)

from app_manager.core.config_checks import validate_app_config
from app_manager.models import AppConfig, ConfigValidationError, ManagerConfig
from app_manager.ui.theme import MESSAGE_BOX_STYLESHEET


APP_PRESETS = {
    "FastAPI / Uvicorn (dev)": {
        "mode": "dev",
        "entry_kind": "uvicorn",
        "entry_target": "main:app",
        "port": 8000,
        "health_url": "http://127.0.0.1:8000/health",
    },
    "Flask / Waitress (dev)": {
        "mode": "dev",
        "entry_kind": "waitress",
        "entry_target": "wsgi:app",
        "port": 8080,
        "health_url": "http://127.0.0.1:8080/health",
    },
    "Nur beobachten": {
        "mode": "observed",
        "entry_kind": "uvicorn",
        "entry_target": "main:app",
        "port": 8000,
        "health_url": "http://127.0.0.1:8000/health",
    },
    "Windows Service": {
        "mode": "prod",
        "entry_kind": "uvicorn",
        "entry_target": "main:app",
        "host": "0.0.0.0",
        "port": 8000,
        "health_url": "http://127.0.0.1:8000/health",
    },
}


class AppConfigDialog(QWizard):
    def __init__(
        self,
        manager_config: ManagerConfig,
        existing_config: AppConfig | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._manager_config = manager_config
        self._existing_config = existing_config
        self._selected_config: AppConfig | None = None
        self._field_widgets: dict[str, object] = {}
        self._last_auto_id: str | None = None
        self._syncing_form = False

        self.setWindowTitle("Edit App" if existing_config is not None else "Add App")
        self.resize(900, 640)
        # ModernStyle paints native white chrome on Windows; ClassicStyle keeps
        # the whole wizard under our stylesheet.
        self.setWizardStyle(QWizard.WizardStyle.ClassicStyle)
        self.setStyleSheet(
            """
            QWizard {
                background: #151719;
                color: #eef2f6;
            }
            QWizardPage {
                background: #151719;
            }
            QWizard QWidget {
                color: #eef2f6;
            }
            QWizard QLabel {
                color: #dce4ed;
            }
            QWizard QLabel#wizardPageTitle {
                color: #f7fafc;
                font-size: 18px;
                font-weight: 700;
            }
            QWizard QLabel#wizardPageSubtitle {
                color: #94a3b8;
            }
            QWizard QLineEdit,
            QWizard QComboBox,
            QWizard QSpinBox {
                min-height: 30px;
                padding: 6px 10px;
                border: 1px solid #3a424a;
                border-radius: 5px;
                background: #111315;
                color: #eef2f6;
                selection-background-color: #31516b;
            }
            QWizard QLineEdit:focus,
            QWizard QComboBox:focus,
            QWizard QSpinBox:focus {
                border-color: #64748b;
            }
            QWizard QComboBox QAbstractItemView {
                background: #1d2023;
                color: #eef2f6;
                border: 1px solid #3a424a;
                selection-background-color: #31516b;
            }
            QWizard QCheckBox {
                color: #dce4ed;
                spacing: 8px;
            }
            QWizard QPushButton {
                min-height: 30px;
                padding: 6px 12px;
                border: 1px solid #3a424a;
                border-radius: 5px;
                background: #252a2f;
                color: #eef2f6;
                font-weight: 600;
            }
            QWizard QPushButton:hover {
                background: #303740;
                border-color: #4b5563;
            }
            QWizard QPushButton:pressed {
                background: #1f2429;
            }
            QWizard QPushButton:disabled {
                border-color: #30363d;
                background: #202326;
                color: #717c89;
            }
            QWizard::title {
                color: #f7fafc;
                font-size: 18px;
                font-weight: 700;
            }
            QWizard::subTitle {
                color: #94a3b8;
            }
            """
        )

        self.addPage(self._basics_page())
        self.addPage(self._runtime_page())
        self.addPage(self._service_page())
        self.addPage(self._review_page())
        self._apply_initial_values()
        self._sync_entry_target_options()
        self.currentIdChanged.connect(lambda _: self._refresh_review())

    @property
    def selected_config(self) -> AppConfig | None:
        return self._selected_config

    def accept(self) -> None:  # type: ignore[override]
        config = self._config_from_form()
        if config is None:
            return

        result = validate_app_config(config)
        if result.errors:
            QMessageBox.critical(self, "Validation Failed", "\n".join(result.errors))
            return
        if result.warnings:
            if not _confirm_validation_warnings(self, result.warnings):
                return

        self._selected_config = config
        super().accept()

    def _new_page(self, title: str, subtitle: str) -> tuple[QWizardPage, QVBoxLayout]:
        page = QWizardPage()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)

        title_label = QLabel(title)
        title_label.setObjectName("wizardPageTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("wizardPageSubtitle")
        subtitle_label.setWordWrap(True)

        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        layout.addSpacing(6)
        return page, layout

    def _basics_page(self) -> QWizardPage:
        page, root_layout = self._new_page("Start", "Pick a template, then adjust only what differs.")
        layout = QFormLayout()
        root_layout.addLayout(layout)
        templates = ["Current config"] if self._existing_config is not None else list(APP_PRESETS)
        self._add_combo(layout, "template", "Template", templates)
        template_box = self._combo_box("template")
        if self._existing_config is None:
            template_box.currentTextChanged.connect(self._apply_preset)
        else:
            template_box.setEnabled(False)
            template_box.setToolTip("Existing configs are shown exactly as saved. Templates are only used when adding a new app.")
        self._add_line(layout, "id", "ID")
        self._line_edit("id").textChanged.connect(self._sync_derived_from_id)
        self._add_line(layout, "display_name", "Display name")
        self._add_combo(layout, "mode", "Mode", ["dev", "prod", "both", "observed"])
        self._mode_hint_label = QLabel()
        self._mode_hint_label.setWordWrap(True)
        layout.addRow(QLabel("Mode help"), self._mode_hint_label)
        self._combo_box("mode").currentTextChanged.connect(lambda _: self._refresh_mode_hint())
        self._add_line(layout, "host", "Host")
        self._add_spin(layout, "port", "Port", 1, 65535)
        self._add_line(layout, "health_url", "Health URL")
        return page

    def _runtime_page(self) -> QWizardPage:
        page, root_layout = self._new_page("Runtime", "Select the project folder and Python environment.")
        layout = QFormLayout()
        root_layout.addLayout(layout)
        self._add_path_line(layout, "repo_path", "Repo path", "folder")
        self._add_line(layout, "branch", "Branch")
        self._add_path_line(layout, "python_path", "Python path", "file", "Python (*.exe);;All files (*)")
        self._add_path_line(layout, "venv_path", "Venv path", "folder")
        self._add_combo(layout, "entry_kind", "Entry kind", ["uvicorn", "waitress"])
        self._combo_box("entry_kind").currentTextChanged.connect(self._sync_entry_target_options)
        self._add_editable_combo(layout, "entry_target", "Entry target", _entry_target_options("uvicorn"))
        self._entry_hint_label = QLabel()
        self._entry_hint_label.setWordWrap(True)
        layout.addRow(QLabel("Entry help"), self._entry_hint_label)
        self._add_path_line(layout, "env_file", "Env file", "file", "Environment (*.env);;All files (*)")
        self._add_path_line(layout, "requirements_file", "Requirements file", "file", "Requirements (*.txt);;All files (*)")
        self._add_line(layout, "init_command", "Init command")
        return page

    def _service_page(self) -> QWizardPage:
        page, root_layout = self._new_page("Service and Logs", "Only needed for prod or both mode.")
        layout = QFormLayout()
        root_layout.addLayout(layout)
        self._add_line(layout, "service_name", "Service name")
        self._add_line(layout, "service_account", "Service account")
        self._add_line(layout, "service_password", "Service password")
        self._line_edit("service_password").setEchoMode(QLineEdit.EchoMode.Password)
        self._add_path_line(layout, "log_dir", "Log dir", "folder")
        self._add_path_line(layout, "winsw_exe_path", "WinSW exe path", "file", "Executable (*.exe);;All files (*)")
        self._add_check(layout, "autostart_prod", "Autostart prod")
        return page

    def _review_page(self) -> QWizardPage:
        page, layout = self._new_page("Review", "Finish validates the config before saving.")
        self._review_label = QLabel()
        self._review_label.setWordWrap(True)
        layout.addWidget(self._review_label)
        return page

    def _apply_initial_values(self) -> None:
        if self._existing_config is not None:
            self._apply_config(self._existing_config)
            return

        self._syncing_form = True
        default_id = "my-app"
        self._line_edit("id").setText(default_id)
        self._line_edit("display_name").setText("My App")
        self._combo_box("mode").setCurrentText("dev")
        self._line_edit("repo_path").setText(str(Path.cwd()))
        self._line_edit("branch").setText("main")
        self._line_edit("python_path").setText(str(Path.cwd() / ".venv" / "Scripts" / "python.exe"))
        self._line_edit("venv_path").setText(str(Path.cwd() / ".venv"))
        self._combo_box("entry_kind").setCurrentText("uvicorn")
        self._combo_box("entry_target").setCurrentText("main:app")
        self._line_edit("host").setText("127.0.0.1")
        self._spin_box("port").setValue(8000)
        self._line_edit("service_name").setText(default_id)
        self._line_edit("service_account").setText("")
        self._line_edit("service_password").setText("")
        self._line_edit("log_dir").setText(str(self._manager_config.logs_dir / default_id))
        self._line_edit("winsw_exe_path").setText(str(self._manager_config.winsw_exe_path))
        self._last_auto_id = default_id
        self._syncing_form = False
        self._refresh_mode_hint()
        self._refresh_entry_hint()
        self._refresh_review()

    def _apply_config(self, config: AppConfig) -> None:
        self._syncing_form = True
        self._line_edit("id").setText(config.id)
        self._line_edit("display_name").setText(config.display_name)
        self._combo_box("mode").setCurrentText(config.mode)
        self._line_edit("repo_path").setText(str(config.repo_path))
        self._line_edit("branch").setText(config.branch)
        self._line_edit("python_path").setText(str(config.python_path))
        self._line_edit("venv_path").setText(str(config.venv_path))
        self._combo_box("entry_kind").setCurrentText(config.entry_kind)
        self._combo_box("entry_target").setCurrentText(config.entry_target)
        self._line_edit("host").setText(config.host)
        self._spin_box("port").setValue(config.port)
        self._line_edit("health_url").setText(config.health_url or "")
        self._line_edit("env_file").setText(str(config.env_file) if config.env_file else "")
        self._line_edit("requirements_file").setText(str(config.requirements_file) if config.requirements_file else "")
        self._line_edit("init_command").setText(config.init_command or "")
        self._line_edit("service_name").setText(config.service_name)
        self._line_edit("service_account").setText(config.service_account or "")
        self._line_edit("service_password").setText(config.service_password or "")
        self._line_edit("log_dir").setText(str(config.log_dir))
        self._line_edit("winsw_exe_path").setText(str(config.winsw_exe_path))
        self._check_box("autostart_prod").setChecked(config.autostart_prod)
        self._last_auto_id = None
        self._syncing_form = False
        self._refresh_mode_hint()
        self._refresh_entry_hint()
        self._refresh_review()

    def _refresh_review(self) -> None:
        if not hasattr(self, "_review_label"):
            return
        mode = self._combo_box("mode").currentText()
        mode_hint = _mode_hint(mode)
        self._review_label.setText(
            "Ready to save:\n\n"
            f"ID: {self._line_edit('id').text().strip()}\n"
            f"Name: {self._line_edit('display_name').text().strip()}\n"
            f"Mode: {mode} ({mode_hint})\n"
            f"Repo: {self._line_edit('repo_path').text().strip()}\n"
            f"Entry: {self._combo_box('entry_kind').currentText()} {self._combo_box('entry_target').currentText().strip()}\n"
            f"Bind: {self._line_edit('host').text().strip()}:{self._spin_box('port').value()}\n"
            f"Health: {self._line_edit('health_url').text().strip() or '-'}\n"
            f"Service: {self._line_edit('service_name').text().strip()}\n"
            f"Service account: {self._line_edit('service_account').text().strip() or '-'}"
        )

    def _config_from_form(self) -> AppConfig | None:
        payload = {
            "id": self._line_edit("id").text().strip(),
            "display_name": self._line_edit("display_name").text().strip(),
            "mode": self._combo_box("mode").currentText(),
            "repo_path": self._line_edit("repo_path").text().strip(),
            "branch": self._line_edit("branch").text().strip(),
            "python_path": self._line_edit("python_path").text().strip(),
            "venv_path": self._line_edit("venv_path").text().strip(),
            "entry_kind": self._combo_box("entry_kind").currentText(),
            "entry_target": self._combo_box("entry_target").currentText().strip(),
            "host": self._line_edit("host").text().strip(),
            "port": self._spin_box("port").value(),
            "health_url": _empty_to_none(self._line_edit("health_url").text()),
            "env_file": _empty_to_none(self._line_edit("env_file").text()),
            "requirements_file": _empty_to_none(self._line_edit("requirements_file").text()),
            "init_command": _empty_to_none(self._line_edit("init_command").text()),
            "service_name": self._line_edit("service_name").text().strip(),
            "service_account": _empty_to_none(self._line_edit("service_account").text()),
            "service_password": _empty_to_none(self._line_edit("service_password").text()),
            "log_dir": self._line_edit("log_dir").text().strip(),
            "winsw_exe_path": self._line_edit("winsw_exe_path").text().strip(),
            "autostart_prod": self._check_box("autostart_prod").isChecked(),
        }
        try:
            return AppConfig.from_dict(payload, base_dir=self._manager_config.apps_dir)
        except ConfigValidationError as exc:
            QMessageBox.critical(self, "Invalid Config", "\n".join(exc.errors))
            return None

    def _add_line(self, layout: QFormLayout, field_name: str, label: str) -> None:
        widget = QLineEdit()
        widget.textChanged.connect(lambda _: self._refresh_review())
        self._field_widgets[field_name] = widget
        layout.addRow(QLabel(label), widget)

    def _add_path_line(
        self,
        layout: QFormLayout,
        field_name: str,
        label: str,
        path_kind: str,
        file_filter: str = "All files (*)",
    ) -> None:
        widget = QLineEdit()
        widget.textChanged.connect(lambda _: self._refresh_review())
        self._field_widgets[field_name] = widget

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(widget, 1)
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(lambda: self._browse_path(field_name, path_kind, file_filter))
        row_layout.addWidget(browse_button)
        layout.addRow(QLabel(label), row)

    def _add_combo(self, layout: QFormLayout, field_name: str, label: str, values: list[str]) -> None:
        widget = QComboBox()
        widget.addItems(values)
        widget.currentTextChanged.connect(lambda _: self._refresh_review())
        self._field_widgets[field_name] = widget
        layout.addRow(QLabel(label), widget)

    def _add_editable_combo(self, layout: QFormLayout, field_name: str, label: str, values: list[str]) -> None:
        widget = QComboBox()
        widget.setEditable(True)
        widget.addItems(values)
        widget.currentTextChanged.connect(lambda _: self._refresh_review())
        self._field_widgets[field_name] = widget
        layout.addRow(QLabel(label), widget)

    def _add_spin(self, layout: QFormLayout, field_name: str, label: str, minimum: int, maximum: int) -> None:
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        widget.valueChanged.connect(lambda _: self._refresh_review())
        self._field_widgets[field_name] = widget
        layout.addRow(QLabel(label), widget)

    def _add_check(self, layout: QFormLayout, field_name: str, label: str) -> None:
        widget = QCheckBox()
        self._field_widgets[field_name] = widget
        layout.addRow(QLabel(label), widget)

    def _line_edit(self, field_name: str) -> QLineEdit:
        return self._field_widgets[field_name]  # type: ignore[return-value]

    def _combo_box(self, field_name: str) -> QComboBox:
        return self._field_widgets[field_name]  # type: ignore[return-value]

    def _spin_box(self, field_name: str) -> QSpinBox:
        return self._field_widgets[field_name]  # type: ignore[return-value]

    def _check_box(self, field_name: str) -> QCheckBox:
        return self._field_widgets[field_name]  # type: ignore[return-value]

    def _sync_entry_target_options(self) -> None:
        widget = self._combo_box("entry_target")
        current_text = widget.currentText().strip()
        options = _entry_target_options(self._combo_box("entry_kind").currentText())
        widget.blockSignals(True)
        widget.clear()
        widget.addItems(options)
        widget.setCurrentText(current_text or options[0])
        widget.blockSignals(False)
        self._refresh_entry_hint()
        self._refresh_review()

    def _apply_preset(self, preset_name: str) -> None:
        if self._existing_config is not None or self._syncing_form:
            return
        preset = APP_PRESETS.get(preset_name)
        if preset is None:
            return
        self._combo_box("mode").setCurrentText(str(preset["mode"]))
        self._combo_box("entry_kind").setCurrentText(str(preset["entry_kind"]))
        self._combo_box("entry_target").setCurrentText(str(preset["entry_target"]))
        if "host" in preset:
            self._line_edit("host").setText(str(preset["host"]))
        self._spin_box("port").setValue(int(preset["port"]))
        self._line_edit("health_url").setText(str(preset["health_url"]))
        self._refresh_mode_hint()
        self._refresh_entry_hint()
        self._refresh_review()

    def _browse_path(self, field_name: str, path_kind: str, file_filter: str) -> None:
        current_text = self._line_edit(field_name).text().strip()
        start_path = current_text or str(Path.cwd())
        if path_kind == "folder":
            selected = QFileDialog.getExistingDirectory(self, "Select Folder", start_path)
        else:
            selected, _ = QFileDialog.getOpenFileName(self, "Select File", start_path, file_filter)
        if selected:
            self._line_edit(field_name).setText(selected)
            if field_name == "repo_path":
                self._fill_common_paths(Path(selected))

    def _fill_common_paths(self, repo_path: Path) -> None:
        venv_path = repo_path / ".venv"
        python_path = venv_path / "Scripts" / "python.exe"
        requirements_path = repo_path / "requirements.txt"
        self._line_edit("venv_path").setText(str(venv_path))
        self._line_edit("python_path").setText(str(python_path))
        if requirements_path.exists() and not self._line_edit("requirements_file").text().strip():
            self._line_edit("requirements_file").setText(str(requirements_path))

    def _sync_derived_from_id(self, value: str) -> None:
        if self._syncing_form:
            return
        app_id = value.strip()
        if not app_id:
            return
        previous_id = self._last_auto_id
        if self._line_edit("display_name").text().strip() in {"", "My App", _display_name(previous_id)}:
            self._line_edit("display_name").setText(_display_name(app_id))
        if self._line_edit("service_name").text().strip() in {"", previous_id or ""}:
            self._line_edit("service_name").setText(app_id)
        previous_log_dir = self._manager_config.logs_dir / previous_id if previous_id else None
        if self._line_edit("log_dir").text().strip() in {"", str(previous_log_dir)}:
            self._line_edit("log_dir").setText(str(self._manager_config.logs_dir / app_id))
        self._last_auto_id = app_id

    def _refresh_mode_hint(self) -> None:
        if hasattr(self, "_mode_hint_label"):
            self._mode_hint_label.setText(_mode_hint(self._combo_box("mode").currentText()))

    def _refresh_entry_hint(self) -> None:
        if hasattr(self, "_entry_hint_label"):
            self._entry_hint_label.setText(_entry_hint(self._combo_box("entry_kind").currentText()))


def _empty_to_none(value: str) -> str | None:
    stripped = value.strip()
    return stripped or None


def _entry_target_options(entry_kind: str) -> list[str]:
    if entry_kind == "waitress":
        return ["wsgi:app", "app:app", "main:app", "server:app", "run:app"]
    return ["main:app", "app:app", "api:app", "app.main:app", "src.main:app"]


def _mode_hint(mode: str) -> str:
    hints = {
        "dev": "App Manager starts a normal local Python process.",
        "prod": "Windows service through WinSW.",
        "both": "Local app process and Windows service are both available. Only one should run at a time on the same port.",
        "observed": "Shows status only; no start, stop, update, or service actions.",
    }
    return hints.get(mode, "Unknown mode.")


def _entry_hint(entry_kind: str) -> str:
    if entry_kind == "waitress":
        return "Use waitress for Flask or other WSGI apps. Typical target: wsgi:app."
    return "Use uvicorn for FastAPI, Starlette, or other ASGI apps. Typical target: main:app."


def _display_name(app_id: str | None) -> str:
    if not app_id:
        return ""
    return app_id.replace("-", " ").replace("_", " ").title()


def _confirm_validation_warnings(parent: QWidget, warnings: list[str]) -> bool:
    message = QMessageBox(parent)
    message.setIcon(QMessageBox.Icon.Warning)
    message.setWindowTitle("Validation Warnings")
    message.setText("The app config can be saved, but App Manager found warnings.")
    message.setInformativeText("\n".join(f"- {warning}" for warning in warnings) + "\n\nSave anyway?")
    message.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    message.setDefaultButton(QMessageBox.StandardButton.No)
    message.setStyleSheet(MESSAGE_BOX_STYLESHEET)
    return message.exec() == QMessageBox.StandardButton.Yes
