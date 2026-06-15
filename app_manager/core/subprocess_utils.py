from __future__ import annotations

import locale
import subprocess
from pathlib import Path
from typing import Any


def run_capture(
    command: Any,
    *,
    cwd: Path | None = None,
    shell: bool = False,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    options = {
        "cwd": cwd,
        "capture_output": True,
        "text": False,
        "shell": shell,
        "check": False,
        "timeout": timeout,
    }
    creation_flags = _background_creation_flags()
    if creation_flags:
        options["creationflags"] = creation_flags

    result = subprocess.run(command, **options)
    return subprocess.CompletedProcess(
        args=result.args,
        returncode=result.returncode,
        stdout=decode_output(result.stdout),
        stderr=decode_output(result.stderr),
    )


def decode_output(payload: bytes | str | None) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload

    encodings = _candidate_encodings()
    for encoding in encodings:
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode(encodings[0], errors="replace")


def _candidate_encodings() -> list[str]:
    preferred = locale.getpreferredencoding(False)
    encodings: list[str] = []
    for encoding in ("utf-8", preferred, "cp1252"):
        normalized = (encoding or "").strip()
        if normalized and normalized.lower() not in {item.lower() for item in encodings}:
            encodings.append(normalized)
    return encodings or ["utf-8"]


def _background_creation_flags() -> int:
    # GUI apps should not flash console windows for background Git,
    # PowerShell, taskkill, pip, or WinSW status commands on Windows.
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)
