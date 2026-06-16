from __future__ import annotations

import ctypes
import shutil
from pathlib import Path
from xml.etree import ElementTree as ET

from app_manager.core.runtime_store import RuntimeStore
from app_manager.core.service_inspect import (
    ServiceInfo,
    ServiceInspector,
    accounts_match,
    network_account_warning,
)
from app_manager.core.subprocess_utils import run_capture
from app_manager.models.config import AppConfig
from app_manager.models.runtime import ActionResult, RuntimeStatus


class ServiceRunner:
    def __init__(self, runtime_root: Path, inspector: ServiceInspector | None = None) -> None:
        self.runtime_root = runtime_root
        self.store = RuntimeStore(runtime_root)
        self.inspector = inspector or ServiceInspector()

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
            return ActionResult(True, self._with_account_warning(config, f"service is already running: {detail}"))
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
        return ActionResult(True, self._with_account_warning(config, f"{install_result.message}; {start_result.message}"))

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
        ET.SubElement(service, "description").text = f"Python WebApp Manager: {config.display_name}"
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

        domain, user = _split_service_account(config.service_account)
        if not user:
            return

        # WinSW v2 (the binary downloaded from the latest stable release)
        # expects <domain> + <user> with a bare account name. The
        # combined <username>DOMAIN\user</username> form is WinSW v3 only and
        # is silently ignored by v2, which then installs the service as
        # LocalSystem - the account never takes effect.
        service_account = ET.SubElement(service, "serviceaccount")
        if domain:
            ET.SubElement(service_account, "domain").text = domain
        ET.SubElement(service_account, "user").text = user
        # Group Managed Service Accounts (account name ending in "$") have no
        # password; everything else uses the configured password when present.
        if config.service_password and not user.endswith("$"):
            ET.SubElement(service_account, "password").text = config.service_password
        ET.SubElement(service_account, "allowservicelogon").text = "true"

    def inspect_service(self, config: AppConfig) -> ServiceInfo:
        return self.inspector.inspect(config.service_name)

    def diagnose(self, config: AppConfig) -> ActionResult:
        if config.mode not in {"prod", "both"}:
            return ActionResult(False, "service diagnostics are only available for prod or both mode")
        try:
            info = self.inspector.inspect(config.service_name)
        except OSError as exc:
            return ActionResult(False, f"service inspection failed: {exc}")

        configured = config.service_account or "LocalSystem (default)"
        lines = [f"Service: {config.service_name}", f"Configured account: {configured}"]
        if not info.exists:
            lines.append("Installed: no (service not found in Windows SCM)")
            return ActionResult(False, "\n".join(lines))

        match = accounts_match(config.service_account, info.start_name)
        net_warning = network_account_warning(info.start_name)
        lines.extend(
            [
                "Installed: yes",
                f"State: {info.state or 'unknown'}",
                f"PID: {info.process_id if info.process_id else '-'}",
                f"BinPath: {info.path_name or '-'}",
                f"Installed account (SERVICE_START_NAME): {info.start_name or 'unknown'}",
                f"Account match: {'yes' if match else 'NO - configured and installed account differ'}",
            ]
        )
        if net_warning:
            lines.append(f"Account scope: WARNING - {net_warning}")
        else:
            lines.append("Account scope: dedicated user account (can present a user identity)")
        return ActionResult(match and net_warning is None, "\n".join(lines))

    def _with_account_warning(self, config: AppConfig, message: str) -> str:
        warning = self._verify_service_account(config)
        if warning:
            return f"{message}; WARNING: {warning}"
        return message

    def _verify_service_account(self, config: AppConfig) -> str | None:
        if not config.service_account:
            return None
        try:
            info = self.inspector.inspect(config.service_name)
        except OSError as exc:
            return f"could not verify installed service account: {exc}"
        if not info.exists:
            return None
        if not accounts_match(config.service_account, info.start_name):
            actual = info.start_name or "unknown"
            return (
                f"installed service account mismatch: configured '{config.service_account}', "
                f"but Windows reports '{actual}'"
            )
        return None

    def _is_admin(self) -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False


def _split_service_account(account: str) -> tuple[str | None, str]:
    """Split a 'DOMAIN\\user' style account into (domain, bare_user).

    A leading '.' or empty domain means the local computer, for which WinSW v2
    wants the domain element omitted. A bare account name has no domain.
    """
    text = (account or "").strip()
    if "\\" in text:
        domain, _, user = text.partition("\\")
        domain = domain.strip()
        user = user.strip()
        if domain in {"", "."}:
            return None, user
        return domain, user
    return None, text


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
