from __future__ import annotations

import ctypes
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

from app_manager.core.runtime_store import RuntimeStore
from app_manager.models.config import AppConfig
from app_manager.models.runtime import ActionResult, RuntimeStatus


class ServiceRunner:
    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = runtime_root
        self.store = RuntimeStore(runtime_root)

    def install_service(self, config: AppConfig) -> ActionResult:
        return self._run_winsw(config, "install", require_admin=True)

    def uninstall_service(self, config: AppConfig) -> ActionResult:
        return self._run_winsw(config, "uninstall", require_admin=True)

    def start_service(self, config: AppConfig) -> ActionResult:
        return self._run_winsw(config, "start")

    def stop_service(self, config: AppConfig) -> ActionResult:
        return self._run_winsw(config, "stop")

    def restart_service(self, config: AppConfig) -> ActionResult:
        stop_result = self.stop_service(config)
        if not stop_result.ok and "stopped" not in stop_result.message.lower():
            return stop_result
        status, detail = self.get_status(config)
        if status == "running":
            return ActionResult(False, f"service is still running after stop: {detail}")
        return self.start_service(config)

    def get_status(self, config: AppConfig) -> tuple[RuntimeStatus, str]:
        result = self._run_winsw(config, "status")
        if not result.ok:
            return "error", result.message

        message = result.message.lower()
        if "active" in message or "running" in message:
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

        xml_path.write_text(ET.tostring(service, encoding="unicode"), encoding="utf-8")
        return xml_path

    def _run_winsw(self, config: AppConfig, command: str, require_admin: bool = False) -> ActionResult:
        if config.mode == "dev":
            return ActionResult(False, "app does not support prod mode")
        if require_admin and not self._is_admin():
            return ActionResult(False, "admin rights are required for this action")
        if not config.winsw_exe_path.exists():
            return ActionResult(False, f"WinSW executable not found: {config.winsw_exe_path}")

        self.write_xml(config)
        result = subprocess.run(
            [str(config.winsw_exe_path), command],
            cwd=self.store.app_dir(config),
            capture_output=True,
            text=True,
            check=False,
        )
        message = result.stdout.strip() or result.stderr.strip() or f"WinSW {command} finished with code {result.returncode}"
        return ActionResult(result.returncode == 0, message)

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

    def _is_admin(self) -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False
