from __future__ import annotations

from subprocess import CompletedProcess
from unittest.mock import patch

from app_manager.core.subprocess_utils import decode_output, run_capture


def test_decode_output_prefers_utf8_for_non_ansi_bytes() -> None:
    assert decode_output(b"M\xc3\xbcnchen") == "München"


def test_run_capture_decodes_utf8_stdout_and_stderr() -> None:
    completed = CompletedProcess(
        args=["git", "status"],
        returncode=0,
        stdout="München".encode("utf-8"),
        stderr="Fehler ä".encode("utf-8"),
    )

    with patch("app_manager.core.subprocess_utils.subprocess.run", return_value=completed):
        result = run_capture(["git", "status"])

    assert result.stdout == "München"
    assert result.stderr == "Fehler ä"
