from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_manager.core.config_checks import validate_app_config
from app_manager.models import AppConfig, ConfigValidationError, DiscoveredApp
from app_manager.ui.theme import MESSAGE_BOX_STYLESHEET, apply_dialog_style


class DiscoveryDialog(QDialog):
    def __init__(
        self,
        config_base_dir: Path,
        discovered_apps: list[DiscoveredApp],
        suggest_config: Any,
        ignore_callback: Callable[[DiscoveredApp], bool],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config_base_dir = config_base_dir
        self._discovered_apps = discovered_apps
        self._suggest_config = suggest_config
        self._ignore_callback = ignore_callback
        self._selected_config: AppConfig | None = None
        self._selected_discovered_app: DiscoveredApp | None = None
        self._field_widgets: dict[str, object] = {}

        self.setWindowTitle("Scan Local Services")
        self.resize(1100, 720)
        apply_dialog_style(self)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(10)
        intro = QLabel("Pick a listener, review the generated config, then save or ignore it.")
        intro.setObjectName("dialogIntro")
        intro.setWordWrap(True)
        root_layout.addWidget(intro)

        splitter = QSplitter(Qt.Horizontal)
        root_layout.addWidget(splitter, 1)

        self.result_table = QTableWidget(0, 8)
        self.result_table.setHorizontalHeaderLabels(
            ["Name", "Port", "PID", "Owner", "Address", "Process", "Parent PID", "Service"]
        )
        self.result_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.result_table.setSelectionMode(QTableWidget.SingleSelection)
        self.result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.result_table.setSortingEnabled(True)
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.itemSelectionChanged.connect(self._on_selection_changed)
        header = self.result_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.Stretch)
        splitter.addWidget(self.result_table)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        splitter.addWidget(right_panel)

        self.detected_label = QLabel("No result selected")
        self.detected_label.setObjectName("dialogHint")
        self.detected_label.setWordWrap(True)
        right_layout.addWidget(self.detected_label)

        self.attach_process_checkbox = QCheckBox("Attach this running process")
        self.attach_process_checkbox.setToolTip("Stores the current PID so Stop App Process can stop it once.")
        right_layout.addWidget(self.attach_process_checkbox)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_container = QWidget()
        scroll_container.setObjectName("dialogSurface")
        self.form_layout = QFormLayout(scroll_container)
        scroll_area.setWidget(scroll_container)
        right_layout.addWidget(scroll_area, 1)

        self._build_form()
        self._combo_box("mode").currentTextChanged.connect(self._sync_attach_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        ignore_button = buttons.addButton("Ignore Selected", QDialogButtonBox.ActionRole)
        ignore_button.clicked.connect(self._ignore_selected)
        self._save_button = buttons.button(QDialogButtonBox.Save)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root_layout.addWidget(buttons)

        self._populate_results(discovered_apps)

        if discovered_apps:
            self.result_table.selectRow(0)
        else:
            self._save_button.setEnabled(False)

    @property
    def selected_config(self) -> AppConfig | None:
        return self._selected_config

    @property
    def selected_discovered_app(self) -> DiscoveredApp | None:
        return self._selected_discovered_app

    @property
    def attach_current_process(self) -> bool:
        return self.attach_process_checkbox.isChecked()

    def set_suggested_payload(self, payload: dict[str, Any]) -> None:
        self._line_edit("id").setText(str(payload["id"]))
        self._line_edit("display_name").setText(str(payload["display_name"]))
        self._combo_box("mode").setCurrentText(str(payload["mode"]))
        self._line_edit("repo_path").setText(str(payload["repo_path"]))
        self._line_edit("branch").setText(str(payload["branch"]))
        self._line_edit("python_path").setText(str(payload["python_path"]))
        self._line_edit("venv_path").setText(str(payload["venv_path"]))
        self._combo_box("entry_kind").setCurrentText(str(payload["entry_kind"]))
        self._combo_box("entry_target").setCurrentText(str(payload["entry_target"]))
        self._line_edit("host").setText(str(payload["host"]))
        self._spin_box("port").setValue(int(payload["port"]))
        self._line_edit("health_url").setText("" if payload["health_url"] is None else str(payload["health_url"]))
        self._line_edit("env_file").setText("" if payload["env_file"] is None else str(payload["env_file"]))
        self._line_edit("requirements_file").setText(
            "" if payload["requirements_file"] is None else str(payload["requirements_file"])
        )
        self._line_edit("init_command").setText("" if payload["init_command"] is None else str(payload["init_command"]))
        self._line_edit("service_name").setText(str(payload["service_name"]))
        self._line_edit("log_dir").setText(str(payload["log_dir"]))
        self._line_edit("winsw_exe_path").setText(str(payload["winsw_exe_path"]))
        self._check_box("autostart_prod").setChecked(bool(payload["autostart_prod"]))

    def _build_form(self) -> None:
        self._add_line("id", "ID")
        self._add_line("display_name", "Display name")
        self._add_combo("mode", "Mode", ["dev", "prod", "both", "observed"])
        self._add_line("repo_path", "Repo path")
        self._add_line("branch", "Branch")
        self._add_line("python_path", "Python path")
        self._add_line("venv_path", "Venv path")
        self._add_combo("entry_kind", "Entry kind", ["uvicorn", "waitress"])
        self._combo_box("entry_kind").currentTextChanged.connect(self._sync_entry_target_options)
        self._add_editable_combo("entry_target", "Entry target", _entry_target_options("uvicorn"))
        self._add_line("host", "Host")
        self._add_spin("port", "Port", 1, 65535)
        self._add_line("health_url", "Health URL")
        self._add_line("env_file", "Env file")
        self._add_line("requirements_file", "Requirements file")
        self._add_line("init_command", "Init command")
        self._add_line("service_name", "Service name")
        self._add_line("log_dir", "Log dir")
        self._add_line("winsw_exe_path", "WinSW exe path")
        self._add_check("autostart_prod", "Autostart prod")

    def _populate_results(self, discovered_apps: list[DiscoveredApp]) -> None:
        self.result_table.setSortingEnabled(False)
        self.result_table.setRowCount(len(discovered_apps))

        for row, app in enumerate(discovered_apps):
            name_item = QTableWidgetItem(app.display_name)
            name_item.setData(Qt.UserRole, app)
            self.result_table.setItem(row, 0, name_item)

            port_item = QTableWidgetItem(str(app.port))
            port_item.setData(Qt.EditRole, app.port)
            self.result_table.setItem(row, 1, port_item)

            pid_item = QTableWidgetItem(str(app.pid))
            pid_item.setData(Qt.EditRole, app.pid)
            self.result_table.setItem(row, 2, pid_item)

            self.result_table.setItem(row, 3, QTableWidgetItem(app.owner or "-"))
            self.result_table.setItem(row, 4, QTableWidgetItem(app.local_address))
            self.result_table.setItem(row, 5, QTableWidgetItem(app.process_name))

            parent_item = QTableWidgetItem("-" if app.parent_pid is None else str(app.parent_pid))
            if app.parent_pid is not None:
                parent_item.setData(Qt.EditRole, app.parent_pid)
            self.result_table.setItem(row, 6, parent_item)

            self.result_table.setItem(row, 7, QTableWidgetItem(app.service_name or "-"))

        self.result_table.setSortingEnabled(True)
        self.result_table.sortItems(1, Qt.AscendingOrder)

    def _on_selection_changed(self) -> None:
        current_row = self.result_table.currentRow()
        if current_row < 0:
            return

        item = self.result_table.item(current_row, 0)
        if item is None:
            return

        app = item.data(Qt.UserRole)
        if not isinstance(app, DiscoveredApp):
            return

        self._selected_discovered_app = app
        self.detected_label.setText(
            f"{app.display_name} | PID {app.pid} | {app.process_name} | "
            f"{app.local_address}:{app.port} | owner={app.owner or '-'} | "
            f"parent={app.parent_pid or '-'} | service={app.service_name or '-'}"
        )
        self.set_suggested_payload(self._suggest_config(app))
        self._sync_attach_checkbox()

    def _save(self) -> None:
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
            "log_dir": self._line_edit("log_dir").text().strip(),
            "winsw_exe_path": self._line_edit("winsw_exe_path").text().strip(),
            "autostart_prod": self._check_box("autostart_prod").isChecked(),
        }
        try:
            config = AppConfig.from_dict(payload, base_dir=self._config_base_dir)
        except ConfigValidationError as exc:
            QMessageBox.critical(self, "Invalid Config", "\n".join(exc.errors))
            return
        result = validate_app_config(config)
        if result.errors:
            QMessageBox.critical(self, "Validation Failed", "\n".join(result.errors))
            return
        if result.warnings:
            if not _confirm_validation_warnings(self, result.warnings):
                return
        self._selected_config = config
        self.accept()

    def _ignore_selected(self) -> None:
        app = self._current_discovered_app()
        if app is None:
            QMessageBox.information(self, "Ignore Scan Result", "Select a scan result first.")
            return

        if not self._ignore_callback(app):
            return

        current_row = self.result_table.currentRow()
        if current_row >= 0:
            self.result_table.removeRow(current_row)

        if self.result_table.rowCount() > 0:
            self.result_table.selectRow(min(current_row, self.result_table.rowCount() - 1))
            self._save_button.setEnabled(True)
        else:
            self.detected_label.setText("All current scan results are ignored.")
            self._save_button.setEnabled(False)

    def _add_line(self, field_name: str, label: str) -> None:
        widget = QLineEdit()
        self._field_widgets[field_name] = widget
        self.form_layout.addRow(QLabel(label), widget)

    def _add_combo(self, field_name: str, label: str, values: list[str]) -> None:
        widget = QComboBox()
        widget.addItems(values)
        self._field_widgets[field_name] = widget
        self.form_layout.addRow(QLabel(label), widget)

    def _add_editable_combo(self, field_name: str, label: str, values: list[str]) -> None:
        widget = QComboBox()
        widget.setEditable(True)
        widget.addItems(values)
        self._field_widgets[field_name] = widget
        self.form_layout.addRow(QLabel(label), widget)

    def _add_spin(self, field_name: str, label: str, minimum: int, maximum: int) -> None:
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        self._field_widgets[field_name] = widget
        self.form_layout.addRow(QLabel(label), widget)

    def _add_check(self, field_name: str, label: str) -> None:
        widget = QCheckBox()
        self._field_widgets[field_name] = widget
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(widget)
        layout.addStretch(1)
        self.form_layout.addRow(QLabel(label), row)

    def _line_edit(self, field_name: str) -> QLineEdit:
        return self._field_widgets[field_name]  # type: ignore[return-value]

    def _combo_box(self, field_name: str) -> QComboBox:
        return self._field_widgets[field_name]  # type: ignore[return-value]

    def _spin_box(self, field_name: str) -> QSpinBox:
        return self._field_widgets[field_name]  # type: ignore[return-value]

    def _check_box(self, field_name: str) -> QCheckBox:
        return self._field_widgets[field_name]  # type: ignore[return-value]

    def _current_discovered_app(self) -> DiscoveredApp | None:
        current_row = self.result_table.currentRow()
        if current_row < 0:
            return None
        item = self.result_table.item(current_row, 0)
        if item is None:
            return None
        app = item.data(Qt.UserRole)
        if not isinstance(app, DiscoveredApp):
            return None
        return app

    def _sync_attach_checkbox(self) -> None:
        app = self._selected_discovered_app
        mode = self._combo_box("mode").currentText()
        can_attach = app is not None and app.service_name is None and mode in {"dev", "both"}
        self.attach_process_checkbox.setEnabled(can_attach)
        self.attach_process_checkbox.setChecked(can_attach)

    def _sync_entry_target_options(self) -> None:
        widget = self._combo_box("entry_target")
        current_text = widget.currentText().strip()
        options = _entry_target_options(self._combo_box("entry_kind").currentText())
        widget.blockSignals(True)
        widget.clear()
        widget.addItems(options)
        widget.setCurrentText(current_text or options[0])
        widget.blockSignals(False)


def _empty_to_none(value: str) -> str | None:
    stripped = value.strip()
    return stripped or None


def _entry_target_options(entry_kind: str) -> list[str]:
    if entry_kind == "waitress":
        return ["wsgi:app", "app:app", "main:app", "server:app", "run:app"]
    return ["main:app", "app:app", "api:app", "app.main:app", "src.main:app"]


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
