from __future__ import annotations

from PySide6.QtWidgets import QWidget


DIALOG_STYLESHEET = """
QDialog,
QWizard {
    background: #151719;
    color: #eef2f6;
}
QDialog QWidget,
QWizard QWidget {
    color: #eef2f6;
}
QDialog QLabel,
QWizard QLabel {
    color: #dce4ed;
}
QLabel#dialogIntro,
QLabel#dialogHint,
QLabel#wizardPageSubtitle {
    color: #94a3b8;
}
QLabel#wizardPageTitle {
    color: #f7fafc;
    font-size: 18px;
    font-weight: 700;
}
QLineEdit,
QComboBox,
QSpinBox {
    min-height: 30px;
    padding: 6px 10px;
    border: 1px solid #3a424a;
    border-radius: 5px;
    background: #111315;
    color: #eef2f6;
    selection-background-color: #31516b;
}
QLineEdit:focus,
QComboBox:focus,
QSpinBox:focus {
    border-color: #64748b;
}
QComboBox QAbstractItemView {
    background: #1d2023;
    color: #eef2f6;
    border: 1px solid #3a424a;
    selection-background-color: #31516b;
}
QCheckBox {
    color: #dce4ed;
    spacing: 8px;
}
QPushButton {
    min-height: 30px;
    padding: 6px 12px;
    border: 1px solid #3a424a;
    border-radius: 5px;
    background: #252a2f;
    color: #eef2f6;
    font-weight: 600;
}
QPushButton:hover {
    background: #303740;
    border-color: #4b5563;
}
QPushButton:pressed {
    background: #1f2429;
}
QPushButton:disabled {
    border-color: #30363d;
    background: #202326;
    color: #717c89;
}
QTableWidget {
    background: #1d2023;
    alternate-background-color: #23272b;
    color: #eef2f6;
    border: 1px solid #353c44;
    border-radius: 5px;
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
QTableCornerButton::section {
    background: #262b30;
    border: 0;
}
QSplitter::handle {
    background: #2c3238;
    width: 1px;
}
QScrollArea,
QWidget#dialogSurface,
QTextEdit,
QTextBrowser {
    background: #111315;
    color: #eef2f6;
    border: 1px solid #353c44;
    border-radius: 5px;
}
QProgressBar {
    background: #111315;
    color: #eef2f6;
    border: 1px solid #353c44;
    border-radius: 5px;
    text-align: center;
}
QProgressBar::chunk {
    background: #1f6f4a;
    border-radius: 4px;
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


MESSAGE_BOX_STYLESHEET = """
QMessageBox {
    background: #151719;
    color: #eef2f6;
}
QMessageBox QLabel {
    color: #eef2f6;
    min-width: 360px;
}
QMessageBox QPushButton {
    min-width: 72px;
    min-height: 30px;
    padding: 4px 12px;
    border: 1px solid #3a424a;
    border-radius: 5px;
    background: #252a2f;
    color: #eef2f6;
    font-weight: 600;
}
QMessageBox QPushButton:hover {
    background: #303740;
    border-color: #4b5563;
}
"""


def apply_dialog_style(widget: QWidget) -> None:
    widget.setStyleSheet(DIALOG_STYLESHEET)
