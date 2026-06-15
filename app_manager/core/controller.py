from __future__ import annotations

import os
import socket
from pathlib import Path

from app_manager.core.discovery import WindowsAppDiscovery
from app_manager.core.health import HealthChecker
from app_manager.core.process_runner import ProcessRunner
from app_manager.core.runtime_store import RuntimeStore
from app_manager.core.service_runner import ServiceRunner
from app_manager.core.updater import AppUpdater
from app_manager.models import ActionResult, AppConfig, AppSnapshot, DiscoveredApp, RuntimeStatus


class AppController:
    def __init__(
        self,
        process_runner: ProcessRunner,
        service_runner: ServiceRunner,
        updater: AppUpdater,
        health_checker: HealthChecker,
        discovery: WindowsAppDiscovery | None = None,
    ) -> None:
        self.process_runner = process_runner
        self.service_runner = service_runner
        self.updater = updater
        self.health_checker = health_checker
        self.discovery = discovery or WindowsAppDiscovery()
        self.runtime_store = RuntimeStore(process_runner.runtime_root)

    def snapshot(self, config: AppConfig) -> AppSnapshot:
        if config.mode == "observed":
            return self._observed_snapshot(config)

        dev_status, dev_detail = self._dev_status(config)
        prod_status, prod_detail = self._prod_status(config)
        status, detail, active_mode = self._resolve_runtime_status(config, dev_status, dev_detail, prod_status, prod_detail)

        issues = self._config_issues(config)
        if issues and status in {"stopped", "unknown"}:
            status = "error"
            detail = "; ".join(issues)
        elif issues and status == "running":
            detail = f"{detail}; config warnings: {'; '.join(issues)}"

        health, health_detail = self.health_checker.check(config.health_url)
        git_state, git_detail = self._git_status(config)
        return AppSnapshot(
            status=status,
            status_detail=detail,
            health=health,
            health_detail=health_detail,
            active_mode=active_mode,
            last_action=self.runtime_store.read_last_action(config),
            git_state=git_state,
            git_detail=git_detail,
            runtime_started_at=self._runtime_started_at(config, active_mode),
        )

    def start_dev(self, config: AppConfig) -> ActionResult:
        return self._record(config, "start_dev", self.process_runner.start_dev(config))

    def stop_dev(self, config: AppConfig) -> ActionResult:
        return self._record(config, "stop_dev", self.process_runner.stop_dev(config))

    def restart_dev(self, config: AppConfig) -> ActionResult:
        return self._record(config, "restart_dev", self.process_runner.restart_dev(config))

    def install_service(self, config: AppConfig) -> ActionResult:
        return self._record(config, "install_service", self.service_runner.install_service(config))

    def uninstall_service(self, config: AppConfig) -> ActionResult:
        return self._record(config, "uninstall_service", self.service_runner.uninstall_service(config))

    def start_service(self, config: AppConfig) -> ActionResult:
        return self._record(config, "start_service", self.service_runner.start_service(config))

    def stop_service(self, config: AppConfig) -> ActionResult:
        return self._record(config, "stop_service", self.service_runner.stop_service(config))

    def restart_service(self, config: AppConfig) -> ActionResult:
        return self._record(config, "restart_service", self.service_runner.restart_service(config))

    def check_health(self, config: AppConfig) -> ActionResult:
        health, detail = self.health_checker.check(config.health_url)
        ok = health in {"healthy", "disabled"}
        return self._record(config, "check_health", ActionResult(ok, f"{health}: {detail}"))

    def open_logs(self, config: AppConfig) -> ActionResult:
        try:
            config.log_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(str(config.log_dir))
        except OSError as exc:
            return self._record(config, "open_logs", ActionResult(False, str(exc)))
        return self._record(config, "open_logs", ActionResult(True, f"opened logs: {config.log_dir}"))

    def update_app(self, config: AppConfig) -> ActionResult:
        if config.mode == "observed":
            return self._record(config, "update_app", ActionResult(False, "observed apps cannot be updated"))

        snapshot = self.snapshot(config)
        if snapshot.active_mode == "dev":
            stop_result = self.process_runner.stop_dev(config)
            if not stop_result.ok:
                return self._record(config, "update_app", stop_result)
        elif snapshot.active_mode == "prod":
            stop_result = self.service_runner.stop_service(config)
            if not stop_result.ok:
                return self._record(config, "update_app", stop_result)

        update_result = self.updater.update(config)
        if not update_result.ok:
            return self._record(config, "update_app", update_result)

        if snapshot.active_mode == "dev":
            restart_result = self.process_runner.start_dev(config)
            if not restart_result.ok:
                return self._record(config, "update_app", restart_result)
            update_result = ActionResult(True, f"{update_result.message}; restarted dev runtime")
        elif snapshot.active_mode == "prod":
            restart_result = self.service_runner.start_service(config)
            if not restart_result.ok:
                return self._record(config, "update_app", restart_result)
            update_result = ActionResult(True, f"{update_result.message}; restarted prod runtime")

        return self._record(config, "update_app", update_result)

    def discover_apps(self) -> list[DiscoveredApp]:
        return self.discovery.discover()

    def suggested_config(self, app: DiscoveredApp) -> dict[str, object]:
        return self.discovery.suggest_config(app)

    def attach_discovered_process(self, config: AppConfig, app: DiscoveredApp) -> ActionResult:
        command = [str(app.executable_path)] if app.executable_path is not None else [app.process_name]
        return self._record(config, "attach_discovered_process", self.process_runner.attach_dev_process(config, app.pid, command))

    def _record(self, config: AppConfig, action_name: str, result: ActionResult) -> ActionResult:
        self.runtime_store.write_last_action(config, action_name, result)
        return result

    def _dev_status(self, config: AppConfig) -> tuple[RuntimeStatus, str]:
        if config.mode in {"prod", "observed"}:
            return "unknown", "dev mode disabled"
        return self.process_runner.get_status(config)

    def _prod_status(self, config: AppConfig) -> tuple[RuntimeStatus, str]:
        if config.mode in {"dev", "observed"}:
            return "unknown", "prod mode disabled"
        return self.service_runner.get_status(config)

    def _resolve_runtime_status(
        self,
        config: AppConfig,
        dev_status: RuntimeStatus,
        dev_detail: str,
        prod_status: RuntimeStatus,
        prod_detail: str,
    ) -> tuple[RuntimeStatus, str, str]:
        if config.mode == "dev":
            active_mode = "dev" if dev_status in {"running", "error"} else "none"
            return dev_status, dev_detail, active_mode

        if config.mode == "prod":
            active_mode = "prod" if prod_status in {"running", "error"} else "none"
            return prod_status, prod_detail, active_mode

        if prod_status == "running":
            return prod_status, prod_detail, "prod"
        if dev_status == "running":
            return dev_status, dev_detail, "dev"
        if dev_status == "error":
            return dev_status, dev_detail, "dev"
        if prod_status == "error":
            return prod_status, prod_detail, "prod"
        if prod_status == "unknown" and dev_status != "unknown":
            return dev_status, dev_detail, "none"
        return prod_status if prod_status != "unknown" else dev_status, prod_detail if prod_detail else dev_detail, "none"

    def _config_issues(self, config: AppConfig) -> list[str]:
        if config.mode == "observed":
            return []

        issues: list[str] = []
        issues.extend(self._path_issue(config.repo_path, "repo_path"))
        issues.extend(self._path_issue(config.python_path, "python_path"))
        issues.extend(self._path_issue(config.venv_path, "venv_path"))
        if config.env_file is not None:
            issues.extend(self._path_issue(config.env_file, "env_file"))
        if config.requirements_file is not None:
            issues.extend(self._path_issue(config.requirements_file, "requirements_file"))
        if config.mode in {"prod", "both"}:
            issues.extend(self._path_issue(config.winsw_exe_path, "winsw_exe_path"))
        return issues

    def _path_issue(self, path: Path, field_name: str) -> list[str]:
        if path.exists():
            return []
        return [f"{field_name} not found: {path}"]

    def _observed_snapshot(self, config: AppConfig) -> AppSnapshot:
        health, health_detail = self.health_checker.check(config.health_url)
        if health == "healthy":
            status: RuntimeStatus = "running"
            detail = health_detail
        elif self._port_open(config.host, config.port):
            status = "running"
            detail = f"port is listening: {config.host}:{config.port}"
        else:
            status = "stopped"
            detail = f"port is not listening: {config.host}:{config.port}"

        return AppSnapshot(
            status=status,
            status_detail=detail,
            health=health,
            health_detail=health_detail,
            active_mode="none",
            last_action=self.runtime_store.read_last_action(config),
            git_state="disabled",
            git_detail="observed app",
            runtime_started_at=None,
        )

    def _port_open(self, host: str, port: int) -> bool:
        check_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                return sock.connect_ex((check_host, port)) == 0
        except OSError:
            return False

    def _git_status(self, config: AppConfig) -> tuple[str, str]:
        checker = getattr(self.updater, "check_status", None)
        if checker is None:
            return "unknown", "git status checker unavailable"
        return checker(config)

    def _runtime_started_at(self, config: AppConfig, active_mode: str) -> str | None:
        if active_mode == "dev":
            return self.runtime_store.read_dev_started_at(config)
        return None
