from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QTextEdit


class LogViewer(QTextEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self._path: Path | None = None

    def set_log_path(self, path: Path | None) -> None:
        self._path = path
        self.refresh()

    def refresh(self) -> None:
        if self._path is None or not self._path.exists():
            text = ""
        else:
            text = self._path.read_text(encoding="utf-8", errors="replace")

        if text != self.toPlainText():
            self.setPlainText(text)
