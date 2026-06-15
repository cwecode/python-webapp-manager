from __future__ import annotations

import subprocess
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


def test_run_capture_hides_background_console_windows() -> None:
    completed = CompletedProcess(args=["git", "status"], returncode=0, stdout=b"", stderr=b"")

    with patch("app_manager.core.subprocess_utils.subprocess.run", return_value=completed) as mocked_run:
        run_capture(["git", "status"])

    expected_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if expected_flags:
        assert mocked_run.call_args.kwargs["creationflags"] == expected_flags
    else:
        assert "creationflags" not in mocked_run.call_args.kwargs
