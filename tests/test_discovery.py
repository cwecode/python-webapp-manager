from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from app_manager.core.discovery import WindowsAppDiscovery
from app_manager.ui.main_window import ScanWorker


def test_discovery_merges_listener_process_and_service() -> None:
    outputs = {
        "Get-NetTCPConnection": json.dumps(
            [
                {"LocalAddress": "127.0.0.1", "LocalPort": 8000, "OwningProcess": 1234},
                {"LocalAddress": "127.0.0.1", "LocalPort": 8000, "OwningProcess": 1234},
            ]
        ),
        "Win32_Process": json.dumps(
            [
                {
                    "Id": 1234,
                    "ProcessName": "python",
                    "Path": r"C:\Projects\Demo\.venv\Scripts\python.exe",
                    "ParentProcessId": 999,
                    "Owner": r"DOMAIN\demo",
                }
            ]
        ),
        "Get-CimInstance": json.dumps(
            [
                {
                    "Name": "demo-service",
                    "DisplayName": "Demo Service",
                    "State": "Running",
                    "ProcessId": 1234,
                    "PathName": r'"C:\tools\WinSW-x64.exe" start',
                }
            ]
        ),
    }

    discovery = WindowsAppDiscovery(shell_runner=lambda script: _script_output(outputs, script))

    result = discovery.discover()

    assert len(result) == 1
    assert result[0].display_name == "Demo Service"
    assert result[0].service_name == "demo-service"
    assert result[0].service_path == r"C:\tools\WinSW-x64.exe"
    assert result[0].executable_path == Path(r"C:\Projects\Demo\.venv\Scripts\python.exe")
    assert result[0].owner == r"DOMAIN\demo"
    assert result[0].parent_pid == 999


def test_suggest_config_uses_python_venv_structure() -> None:
    discovery = WindowsAppDiscovery(shell_runner=lambda script: "[]")
    app = discovery.discover()
    assert app == []

    payload = discovery.suggest_config(
        type(
            "Discovered",
            (),
            {
                "service_name": None,
                "service_display_name": None,
                "display_name": "Demo App",
                "process_name": "python",
                "local_address": "127.0.0.1",
                "port": 9000,
                "executable_path": Path(r"C:\Projects\Demo\.venv\Scripts\python.exe"),
                "service_path": None,
            },
        )()
    )

    assert payload["id"] == "demo-app"
    assert payload["mode"] == "dev"
    assert payload["repo_path"] == r"C:\Projects\Demo"
    assert payload["python_path"] == r"C:\Projects\Demo\.venv\Scripts\python.exe"
    assert payload["venv_path"] == r"C:\Projects\Demo\.venv"
    assert payload["winsw_exe_path"] == r"tools\WinSW-x64.exe"


def test_suggest_config_falls_back_to_valid_defaults() -> None:
    discovery = WindowsAppDiscovery(shell_runner=lambda script: "[]")

    payload = discovery.suggest_config(
        type(
            "Discovered",
            (),
            {
                "service_name": "my-service",
                "service_display_name": "My Service",
                "display_name": "My Service",
                "process_name": "svchost",
                "local_address": "0.0.0.0",
                "port": 8080,
                "executable_path": None,
                "service_path": r"C:\tools\WinSW-x64.exe",
            },
        )()
    )

    assert payload["mode"] == "prod"
    assert payload["repo_path"] == "."
    assert payload["python_path"] == r".venv\Scripts\python.exe"
    assert payload["service_name"] == "my-service"
    assert payload["winsw_exe_path"] == r"C:\tools\WinSW-x64.exe"


def test_suggest_config_keeps_non_winsw_services_out_of_prod_mode() -> None:
    discovery = WindowsAppDiscovery(shell_runner=lambda script: "[]")

    payload = discovery.suggest_config(
        type(
            "Discovered",
            (),
            {
                "service_name": "existing-service",
                "service_display_name": "Existing Service",
                "display_name": "Existing Service",
                "process_name": "myservice",
                "local_address": "127.0.0.1",
                "port": 5000,
                "executable_path": None,
                "service_path": r"C:\Program Files\MyService\service.exe",
            },
        )()
    )

    assert payload["mode"] == "dev"
    assert payload["winsw_exe_path"] == r"tools\WinSW-x64.exe"


def test_discovery_treats_missing_shell_output_as_empty_result() -> None:
    discovery = WindowsAppDiscovery(shell_runner=lambda script: None)

    assert discovery.discover() == []


def test_run_powershell_decodes_utf8_output_without_crashing() -> None:
    discovery = WindowsAppDiscovery()
    completed = CompletedProcess(args=["powershell"], returncode=0, stdout='[{"Id":1}]', stderr="")

    with patch("app_manager.core.discovery.run_capture", return_value=completed) as mocked_run:
        output = discovery._run_powershell("Get-Process")

    assert output == '[{"Id":1}]'
    assert mocked_run.called


def test_scan_worker_reports_unexpected_exception_through_failed_signal() -> None:
    class _BrokenController:
        def discover_apps(self) -> list[object]:
            raise RuntimeError("boom")

    worker = ScanWorker(_BrokenController())  # type: ignore[arg-type]
    failures: list[str] = []
    worker.failed.connect(failures.append)

    worker.run()

    assert failures == ["boom"]


def _script_output(outputs: dict[str, str], script: str) -> str:
    for key, output in outputs.items():
        if key in script:
            return output
    raise AssertionError(f"unexpected script: {script}")
