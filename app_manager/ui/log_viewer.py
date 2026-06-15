from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QTextEdit

MAX_LOG_BYTES = 65536


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
            text = self._read_tail(self._path)

        if text != self.toPlainText():
            self.setPlainText(text)

    def _read_tail(self, path: Path) -> str:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > MAX_LOG_BYTES:
                handle.seek(-MAX_LOG_BYTES, 2)
                payload = handle.read()
                return "[showing last 64 KB]\n" + payload.decode("utf-8", errors="replace")
            return handle.read().decode("utf-8", errors="replace")
