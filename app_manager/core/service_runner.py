from __future__ import annotations

import ctypes
import shutil
from pathlib import Path
from xml.etree import ElementTree as ET

from app_manager.core.runtime_store import RuntimeStore
from app_manager.core.subprocess_utils import run_capture
from app_manager.models.config import AppConfig
from app_manager.models.runtime import ActionResult, RuntimeStatus


class ServiceRunner:
    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = runtime_root
        self.store = RuntimeStore(runtime_root)

    def install_service(self, config: AppConfig) -> ActionResult:
        result = self._run_winsw(config, "install", require_admin=True)
        if result.ok or not _service_already_exists(result.message):
            return result

        stop_result = self._run_winsw(config, "stop")
        if not stop_result.ok and not (_service_already_stopped(stop_result.message) or _service_not_installed(stop_result.message)):
            return ActionResult(False, f"{result.message}; failed to stop existing service before reinstall: {stop_result.message}")

        uninstall_result = self.uninstall_service(config)
        if not uninstall_result.ok and not _service_not_installed(uninstall_result.message):
            return ActionResult(False, f"{result.message}; failed to uninstall existing service before reinstall: {uninstall_result.message}")

        retry_result = self._run_winsw(config, "install", require_admin=True)
        if not retry_result.ok:
            return retry_result
        return ActionResult(True, f"existing service removed; {retry_result.message}")

    def uninstall_service(self, config: AppConfig) -> ActionResult:
        return self._run_winsw(config, "uninstall", require_admin=True)

    def start_service(self, config: AppConfig) -> ActionResult:
        status, detail = self.get_status(config)
        if status == "running":
            return ActionResult(True, f"service is already running: {detail}")
        if status == "error":
            return ActionResult(False, detail)

        if not _service_not_installed(detail):
            uninstall_result = self.uninstall_service(config)
            if not uninstall_result.ok and not _service_not_installed(uninstall_result.message):
                return uninstall_result

        install_result = self.install_service(config)
        if not install_result.ok:
            return install_result

        start_result = self._run_winsw(config, "start")
        if not start_result.ok:
            return start_result
        return ActionResult(True, f"{install_result.message}; {start_result.message}")

    def stop_service(self, config: AppConfig) -> ActionResult:
        result = self._run_winsw(config, "stop")
        if not result.ok and _service_not_installed(result.message):
            return ActionResult(True, "service is not installed")
        if not result.ok and not _service_already_stopped(result.message):
            return result

        uninstall_result = self.uninstall_service(config)
        if not uninstall_result.ok and not _service_not_installed(uninstall_result.message):
            return uninstall_result
        if not result.ok:
            return ActionResult(True, uninstall_result.message)
        return ActionResult(True, f"{result.message}; {uninstall_result.message}")

    def restart_service(self, config: AppConfig) -> ActionResult:
        stop_result = self.stop_service(config)
        if not stop_result.ok:
            return stop_result
        start_result = self.start_service(config)
        if not start_result.ok:
            return start_result
        return ActionResult(True, f"{stop_result.message}; {start_result.message}")

    def get_status(self, config: AppConfig) -> tuple[RuntimeStatus, str]:
        result = self._run_winsw(config, "status")
        if not result.ok:
            if _service_not_installed(result.message):
                return "stopped", "service is not installed"
            return "error", result.message

        message = result.message.lower()
        if "active" in message or "running" in message or "started" in message:
            return "running", result.message
        if "stopped" in message:
            return "stopped", result.message
        return "unknown", result.message

    def write_xml(self, config: AppConfig) -> Path:
        runtime_dir = self.store.app_dir(config)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        xml_path = runtime_dir / f"{config.service_name}.xml"

        service = ET.Element("service")
        ET.SubElement(service, "id").text = config.service_name
        ET.SubElement(service, "name").text = config.display_name
        ET.SubElement(service, "description").text = f"Managed by App Manager: {config.display_name}"
        ET.SubElement(service, "executable").text = self._service_executable(config)
        ET.SubElement(service, "arguments").text = " ".join(self._service_arguments(config))
        ET.SubElement(service, "workingdirectory").text = str(config.repo_path)
        ET.SubElement(service, "logpath").text = str(config.log_dir)
        ET.SubElement(service, "logmode").text = "roll"
        ET.SubElement(service, "onfailure", action="restart")
        ET.SubElement(service, "startmode").text = "Automatic" if config.autostart_prod else "Manual"
        self._append_service_account(service, config)

        xml_path.write_text(ET.tostring(service, encoding="unicode"), encoding="utf-8")
        return xml_path

    def _run_winsw(self, config: AppConfig, command: str, require_admin: bool = False) -> ActionResult:
        if config.mode == "dev":
            return ActionResult(False, "app does not support prod mode")
        if config.mode == "observed":
            return ActionResult(False, "observed apps do not support service actions")
        if require_admin and not self._is_admin():
            return ActionResult(False, "admin rights are required for this action")
        if not config.winsw_exe_path.exists():
            return ActionResult(False, f"WinSW executable not found: {config.winsw_exe_path}")

        self.write_xml(config)
        try:
            wrapper_exe_path = self._ensure_wrapper_exe(config)
        except OSError as exc:
            return ActionResult(False, f"failed to prepare WinSW wrapper: {exc}")
        result = run_capture(
            [str(wrapper_exe_path), command],
            cwd=self.store.app_dir(config),
        )
        message = result.stdout.strip() or result.stderr.strip() or f"WinSW {command} finished with code {result.returncode}"
        return ActionResult(result.returncode == 0, message)

    def _ensure_wrapper_exe(self, config: AppConfig) -> Path:
        target_path = self._wrapper_exe_path(config)
        source_path = config.winsw_exe_path.resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if source_path == target_path.resolve():
            return target_path
        if not target_path.exists() or source_path.stat().st_size != target_path.stat().st_size:
            shutil.copy2(source_path, target_path)
        return target_path

    def _wrapper_exe_path(self, config: AppConfig) -> Path:
        return self.store.app_dir(config) / f"{config.service_name}.exe"

    def _service_arguments(self, config: AppConfig) -> list[str]:
        if config.entry_kind == "uvicorn":
            return [
                "-m",
                "uvicorn",
                config.entry_target,
                "--host",
                config.host,
                "--port",
                str(config.port),
            ]

        return [
            "--host",
            config.host,
            "--port",
            str(config.port),
            config.entry_target,
        ]

    def _service_executable(self, config: AppConfig) -> str:
        if config.entry_kind == "uvicorn":
            return str(config.python_path)

        waitress_exe = config.venv_path / "Scripts" / "waitress-serve.exe"
        if waitress_exe.exists():
            return str(waitress_exe)
        return "waitress-serve"

    def _append_service_account(self, service: ET.Element, config: AppConfig) -> None:
        if not config.service_account:
            return

        service_account = ET.SubElement(service, "serviceaccount")
        ET.SubElement(service_account, "username").text = config.service_account
        if config.service_password:
            ET.SubElement(service_account, "password").text = config.service_password
        ET.SubElement(service_account, "allowservicelogon").text = "true"

    def _is_admin(self) -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False


def _service_not_installed(message: str) -> bool:
    normalized = message.lower()
    return (
        "not an installed service" in normalized
        or "does not exist as an installed service" in normalized
        or "service is not installed" in normalized
        or "kein installierter dienst" in normalized
        or "ist kein installierter dienst" in normalized
    )


def _service_already_exists(message: str) -> bool:
    normalized = message.lower()
    return (
        "already exists" in normalized
        or "already installed" in normalized
        or "dienst ist bereits vorhanden" in normalized
        or "bereits vorhanden" in normalized
    )


def _service_already_stopped(message: str) -> bool:
    normalized = message.lower()
    return (
        "already stopped" in normalized
        or "service is stopped" in normalized
        or "not running" in normalized
        or "is not running" in normalized
        or "nicht gestartet" in normalized
        or "nicht ausgeführt" in normalized
    )
