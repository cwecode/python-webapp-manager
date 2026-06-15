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


class _FakeExternalProcessRunner(_FakeProcessRunner):
    def __init__(self, runtime_root: Path, status: tuple[str, str], external_pid: int | None) -> None:
        super().__init__(runtime_root, status)
        self.external_pid = external_pid

    def find_listening_pid(self, config: AppConfig) -> int | None:
        self.calls.append("find_listening_pid")
        return self.external_pid

    def stop_listening_process(self, config: AppConfig) -> ActionResult:
        self.calls.append("stop_listening_process")
        return ActionResult(True, f"force stopped external PID {self.external_pid}")


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


class _FakePreflightUpdater(_FakeUpdater):
    def __init__(self, preflight: ActionResult, result: ActionResult | None = None) -> None:
        super().__init__(result)
        self.preflight = preflight

    def check_update_preconditions(self, config: AppConfig) -> ActionResult:
        self.calls.append("check_update_preconditions")
        return self.preflight


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


def test_update_app_checks_git_before_stopping_runtime(tmp_path: Path) -> None:
    config = _make_config(tmp_path, mode="both")
    process_runner = _FakeProcessRunner(tmp_path / "runtime", ("running", "PID 1234"))
    service_runner = _FakeServiceRunner(("stopped", "service is stopped"))
    updater = _FakePreflightUpdater(ActionResult(False, "working tree is dirty"))
    controller = AppController(process_runner, service_runner, updater, _FakeHealthChecker())

    result = controller.update_app(config)

    assert result.ok is False
    assert result.message == "working tree is dirty"
    assert process_runner.calls == []
    assert service_runner.calls == []
    assert updater.calls == ["check_update_preconditions"]


def test_snapshot_includes_dev_runtime_started_at(tmp_path: Path) -> None:
    config = _make_config(tmp_path, mode="dev")
    runtime_root = tmp_path / "runtime"
    state_dir = runtime_root / config.id
    state_dir.mkdir(parents=True)
    started_at = "2026-06-15T08:30:00+00:00"
    (state_dir / "dev_state.json").write_text(json.dumps({"pid": 1234, "started_at": started_at}), encoding="utf-8")
    process_runner = _FakeProcessRunner(runtime_root, ("running", "PID 1234"))
    service_runner = _FakeServiceRunner(("unknown", "prod mode disabled"))
    controller = AppController(process_runner, service_runner, _FakeUpdater(), _FakeHealthChecker())

    snapshot = controller.snapshot(config)

    assert snapshot.runtime_started_at == started_at


def test_snapshot_reports_external_port_listener(tmp_path: Path) -> None:
    config = _make_config(tmp_path, mode="both")
    process_runner = _FakeExternalProcessRunner(tmp_path / "runtime", ("stopped", "no dev process tracked"), 4321)
    service_runner = _FakeServiceRunner(("stopped", "service is stopped"))
    controller = AppController(process_runner, service_runner, _FakeUpdater(), _FakeHealthChecker())

    snapshot = controller.snapshot(config)

    assert snapshot.status == "running"
    assert snapshot.active_mode == "unknown"
    assert "external PID 4321" in snapshot.status_detail
    assert process_runner.calls == ["get_status", "find_listening_pid"]


def test_stop_external_process_delegates_to_process_runner(tmp_path: Path) -> None:
    config = _make_config(tmp_path, mode="both")
    process_runner = _FakeExternalProcessRunner(tmp_path / "runtime", ("stopped", "no dev process tracked"), 4321)
    service_runner = _FakeServiceRunner(("stopped", "service is stopped"))
    controller = AppController(process_runner, service_runner, _FakeUpdater(), _FakeHealthChecker())

    result = controller.stop_external_process(config)

    assert result.ok is True
    assert result.message == "force stopped external PID 4321"
    assert process_runner.calls == ["stop_listening_process"]
