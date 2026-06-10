from __future__ import annotations

import json
from pathlib import Path

from app_manager.core.controller import AppController
from app_manager.models import ActionResult, AppConfig


class _FakeProcessRunner:
    def __init__(self, runtime_root: Path, status: tuple[str, str]) -> None:
        self.runtime_root = runtime_root
        self._status = status
        self.calls: list[str] = []

    def get_status(self, config: AppConfig) -> tuple[str, str]:
        self.calls.append("get_status")
        return self._status

    def start_dev(self, config: AppConfig) -> ActionResult:
        self.calls.append("start_dev")
        return ActionResult(True, "started dev")

    def stop_dev(self, config: AppConfig) -> ActionResult:
        self.calls.append("stop_dev")
        return ActionResult(True, "stopped dev")

    def restart_dev(self, config: AppConfig) -> ActionResult:
        self.calls.append("restart_dev")
        return ActionResult(True, "restarted dev")


class _FakeServiceRunner:
    def __init__(self, status: tuple[str, str]) -> None:
        self._status = status
        self.calls: list[str] = []

    def get_status(self, config: AppConfig) -> tuple[str, str]:
        self.calls.append("get_status")
        return self._status

    def install_service(self, config: AppConfig) -> ActionResult:
        self.calls.append("install_service")
        return ActionResult(True, "installed service")

    def uninstall_service(self, config: AppConfig) -> ActionResult:
        self.calls.append("uninstall_service")
        return ActionResult(True, "uninstalled service")

    def start_service(self, config: AppConfig) -> ActionResult:
        self.calls.append("start_service")
        return ActionResult(True, "started service")

    def stop_service(self, config: AppConfig) -> ActionResult:
        self.calls.append("stop_service")
        return ActionResult(True, "stopped service")

    def restart_service(self, config: AppConfig) -> ActionResult:
        self.calls.append("restart_service")
        return ActionResult(True, "restarted service")


class _FakeUpdater:
    def __init__(self, result: ActionResult | None = None) -> None:
        self.result = result or ActionResult(True, "update completed")
        self.calls: list[str] = []

    def update(self, config: AppConfig) -> ActionResult:
        self.calls.append("update")
        return self.result


class _FakeHealthChecker:
    def check(self, url: str | None, timeout: float = 2.0) -> tuple[str, str]:
        return "disabled", "no health URL configured"


def _make_config(tmp_path: Path, mode: str = "both") -> AppConfig:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    python_path = tmp_path / ".venv" / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("", encoding="utf-8")
    venv_path = tmp_path / ".venv"
    winsw_path = tmp_path / "tools" / "WinSW-x64.exe"
    winsw_path.parent.mkdir(parents=True)
    winsw_path.write_text("", encoding="utf-8")

    return AppConfig(
        id="demo",
        display_name="Demo App",
        mode=mode,  # type: ignore[arg-type]
        repo_path=repo_path,
        branch="main",
        python_path=python_path,
        venv_path=venv_path,
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
        winsw_exe_path=winsw_path,
        autostart_prod=False,
    )


def test_snapshot_reports_missing_paths_as_error(tmp_path: Path) -> None:
    config = _make_config(tmp_path, mode="dev")
    config.repo_path = tmp_path / "missing-repo"

    process_runner = _FakeProcessRunner(tmp_path / "runtime", ("stopped", "no dev process tracked"))
    service_runner = _FakeServiceRunner(("unknown", "prod mode disabled"))
    controller = AppController(process_runner, service_runner, _FakeUpdater(), _FakeHealthChecker())

    snapshot = controller.snapshot(config)

    assert snapshot.status == "error"
    assert "repo_path not found" in snapshot.status_detail
    assert snapshot.last_action is None


def test_update_app_restarts_active_dev_runtime_and_records_last_action(tmp_path: Path) -> None:
    config = _make_config(tmp_path, mode="both")
    process_runner = _FakeProcessRunner(tmp_path / "runtime", ("running", "PID 1234"))
    service_runner = _FakeServiceRunner(("stopped", "service is stopped"))
    updater = _FakeUpdater()
    controller = AppController(process_runner, service_runner, updater, _FakeHealthChecker())

    result = controller.update_app(config)

    assert result.ok is True
    assert process_runner.calls == ["get_status", "stop_dev", "start_dev"]
    assert service_runner.calls == ["get_status"]
    assert updater.calls == ["update"]

    action_path = tmp_path / "runtime" / config.id / "last_action.json"
    payload = json.loads(action_path.read_text(encoding="utf-8"))
    assert payload["name"] == "update_app"
    assert payload["ok"] is True


def test_update_app_keeps_stopped_runtime_stopped(tmp_path: Path) -> None:
    config = _make_config(tmp_path, mode="both")
    process_runner = _FakeProcessRunner(tmp_path / "runtime", ("stopped", "no dev process tracked"))
    service_runner = _FakeServiceRunner(("stopped", "service is stopped"))
    updater = _FakeUpdater()
    controller = AppController(process_runner, service_runner, updater, _FakeHealthChecker())

    result = controller.update_app(config)

    assert result.ok is True
    assert process_runner.calls == ["get_status"]
    assert service_runner.calls == ["get_status"]
    assert updater.calls == ["update"]
