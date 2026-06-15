from __future__ import annotations

import json
from pathlib import Path

from app_manager.core.process_runner import ProcessRunner
from app_manager.models import AppConfig


def _make_config(tmp_path: Path, mode: str = "dev") -> AppConfig:
    python_path = tmp_path / ".venv" / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("", encoding="utf-8")

    return AppConfig(
        id="demo",
        display_name="Demo App",
        mode=mode,  # type: ignore[arg-type]
        repo_path=tmp_path / "repo",
        branch="main",
        python_path=python_path,
        venv_path=tmp_path / ".venv",
        entry_kind="uvicorn",
        entry_target="main:app",
        host="127.0.0.1",
        port=8000,
        health_url=None,
        env_file=None,
        requirements_file=None,
        init_command=None,
        service_name="demo-service",
        log_dir=tmp_path / "logs",
        winsw_exe_path=tmp_path / "tools" / "WinSW-x64.exe",
        autostart_prod=False,
    )


def test_attach_dev_process_writes_runtime_state_for_running_pid(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = ProcessRunner(tmp_path / "runtime")
    runner._pid_running = lambda pid: pid == 1234  # type: ignore[method-assign]

    result = runner.attach_dev_process(config, 1234, ["python.exe"])

    assert result.ok is True
    state_path = tmp_path / "runtime" / "demo" / "dev_state.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["pid"] == 1234
    assert payload["attached"] is True
    assert payload["command"] == ["python.exe"]


def test_attach_dev_process_rejects_stopped_pid(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = ProcessRunner(tmp_path / "runtime")
    runner._pid_running = lambda pid: False  # type: ignore[method-assign]

    result = runner.attach_dev_process(config, 1234)

    assert result.ok is False
    assert "not running" in result.message


def test_find_listening_pid_matches_loopback_to_wildcard_listener(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = ProcessRunner(tmp_path / "runtime")
    runner._load_tcp_listeners = lambda port: [  # type: ignore[method-assign]
        {"LocalAddress": "0.0.0.0", "LocalPort": port, "OwningProcess": 4321}
    ]

    assert runner.find_listening_pid(config) == 4321


def test_stop_listening_process_force_kills_detected_pid(monkeypatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = ProcessRunner(tmp_path / "runtime")
    runner.find_listening_pid = lambda config: 4321  # type: ignore[method-assign]
    commands: list[list[str]] = []

    def fake_run_capture(command: list[str]):
        commands.append(command)
        return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    monkeypatch.setattr("app_manager.core.process_runner.run_capture", fake_run_capture)

    result = runner.stop_listening_process(config)

    assert result.ok is True
    assert result.message == "force stopped external PID 4321"
    assert commands == [["taskkill", "/F", "/PID", "4321", "/T"]]
