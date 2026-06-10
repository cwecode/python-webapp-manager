from __future__ import annotations

import os
from pathlib import Path

from app_manager.core.health import HealthChecker
from app_manager.core.process_runner import ProcessRunner
from app_manager.core.runtime_store import RuntimeStore
from app_manager.core.service_runner import ServiceRunner
from app_manager.core.updater import AppUpdater
from app_manager.models import ActionResult, AppConfig, AppSnapshot, RuntimeStatus


class AppController:
    def __init__(
        self,
        process_runner: ProcessRunner,
        service_runner: ServiceRunner,
        updater: AppUpdater,
        health_checker: HealthChecker,
    ) -> None:
        self.process_runner = process_runner
        self.service_runner = service_runner
        self.updater = updater
        self.health_checker = health_checker
        self.runtime_store = RuntimeStore(process_runner.runtime_root)

    def snapshot(self, config: AppConfig) -> AppSnapshot:
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
        return AppSnapshot(
            status=status,
            status_detail=detail,
            health=health,
            health_detail=health_detail,
            active_mode=active_mode,
            last_action=self.runtime_store.read_last_action(config),
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

    def _record(self, config: AppConfig, action_name: str, result: ActionResult) -> ActionResult:
        self.runtime_store.write_last_action(config, action_name, result)
        return result

    def _dev_status(self, config: AppConfig) -> tuple[RuntimeStatus, str]:
        if config.mode == "prod":
            return "unknown", "dev mode disabled"
        return self.process_runner.get_status(config)

    def _prod_status(self, config: AppConfig) -> tuple[RuntimeStatus, str]:
        if config.mode == "dev":
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
