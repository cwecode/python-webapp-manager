from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET
from subprocess import CompletedProcess

from app_manager.core.service_inspect import ServiceInfo
from app_manager.core.service_runner import ServiceRunner
from app_manager.models import ActionResult, AppConfig


class _StubInspector:
    def __init__(self, info: ServiceInfo) -> None:
        self.info = info
        self.calls: list[str] = []

    def inspect(self, service_name: str) -> ServiceInfo:
        self.calls.append(service_name)
        return self.info


def _make_config(tmp_path: Path) -> AppConfig:
    python_path = tmp_path / ".venv" / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True, exist_ok=True)
    python_path.write_text("", encoding="utf-8")
    winsw_path = tmp_path / "tools" / "WinSW-x64.exe"
    winsw_path.parent.mkdir(parents=True, exist_ok=True)
    winsw_path.write_text("", encoding="utf-8")

    return AppConfig(
        id="demo",
        display_name="Demo App",
        mode="prod",
        repo_path=tmp_path / "repo",
        branch="main",
        python_path=python_path,
        venv_path=tmp_path / ".venv",
        entry_kind="waitress",
        entry_target="wsgi:app",
        host="127.0.0.1",
        port=8080,
        health_url=None,
        env_file=None,
        requirements_file=None,
        init_command=None,
        service_name="demo-service",
        service_account=None,
        service_password=None,
        log_dir=tmp_path / "logs",
        winsw_exe_path=winsw_path,
        autostart_prod=False,
    )


def test_write_xml_uses_waitress_serve_executable(tmp_path: Path) -> None:
    waitress_exe = tmp_path / ".venv" / "Scripts" / "waitress-serve.exe"
    waitress_exe.parent.mkdir(parents=True)
    waitress_exe.write_text("", encoding="utf-8")
    config = _make_config(tmp_path)
    runner = ServiceRunner(tmp_path / "runtime")

    xml_path = runner.write_xml(config)
    service = ET.fromstring(xml_path.read_text(encoding="utf-8"))

    assert service.findtext("executable") == str(waitress_exe)
    assert service.findtext("arguments") == "--host 127.0.0.1 --port 8080 wsgi:app"
    assert service.find("serviceaccount") is None


def test_write_xml_local_account_uses_winsw_v2_schema_without_domain(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    config.service_account = r".\Jobserver"
    config.service_password = "secret"
    runner = ServiceRunner(tmp_path / "runtime")

    xml_path = runner.write_xml(config)
    service = ET.fromstring(xml_path.read_text(encoding="utf-8"))
    service_account = service.find("serviceaccount")

    assert service_account is not None
    # WinSW v2 expects <user> (bare name) + optional <domain>, not <username>.
    assert service_account.find("username") is None
    assert service_account.findtext("domain") is None
    assert service_account.findtext("user") == "Jobserver"
    assert service_account.findtext("password") == "secret"
    assert service_account.findtext("allowservicelogon") == "true"


def test_write_xml_domain_account_splits_into_domain_and_user(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    config.service_account = r"igefa\jobserver"
    config.service_password = "secret"
    runner = ServiceRunner(tmp_path / "runtime")

    xml_path = runner.write_xml(config)
    service_account = ET.fromstring(xml_path.read_text(encoding="utf-8")).find("serviceaccount")

    assert service_account is not None
    assert service_account.findtext("domain") == "igefa"
    assert service_account.findtext("user") == "jobserver"
    assert service_account.findtext("password") == "secret"


def test_write_xml_gmsa_account_omits_password(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    config.service_account = r"igefa\svc-jobs$"
    config.service_password = "ignored"
    runner = ServiceRunner(tmp_path / "runtime")

    xml_path = runner.write_xml(config)
    service_account = ET.fromstring(xml_path.read_text(encoding="utf-8")).find("serviceaccount")

    assert service_account is not None
    assert service_account.findtext("user") == "svc-jobs$"
    assert service_account.find("password") is None


def test_run_winsw_uses_service_named_wrapper_next_to_xml(monkeypatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    config.winsw_exe_path.write_bytes(b"winsw")
    runner = ServiceRunner(tmp_path / "runtime")
    calls: list[tuple[list[str], Path | None]] = []

    def fake_run_capture(command: list[str], *, cwd: Path | None = None, **kwargs) -> CompletedProcess:
        calls.append((command, cwd))
        return CompletedProcess(command, 0, stdout="Stopped", stderr="")

    monkeypatch.setattr("app_manager.core.service_runner.run_capture", fake_run_capture)

    result = runner._run_winsw(config, "status")

    runtime_dir = tmp_path / "runtime" / "demo"
    wrapper_path = runtime_dir / "demo-service.exe"
    assert result.ok is True
    assert wrapper_path.read_bytes() == b"winsw"
    assert (runtime_dir / "demo-service.xml").exists()
    assert calls == [([str(wrapper_path), "status"], runtime_dir)]


def test_get_status_treats_not_installed_service_as_stopped(monkeypatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = ServiceRunner(tmp_path / "runtime")

    def fake_run_winsw(config: AppConfig, command: str, require_admin: bool = False):
        return ActionResult(False, "FATAL - Der angegebene Dienst ist kein installierter Dienst.")

    monkeypatch.setattr(runner, "_run_winsw", fake_run_winsw)

    assert runner.get_status(config) == ("stopped", "service is not installed")


def test_get_status_treats_winsw_started_as_running(monkeypatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = ServiceRunner(tmp_path / "runtime")

    def fake_run_winsw(config: AppConfig, command: str, require_admin: bool = False):
        return ActionResult(True, "Started")

    monkeypatch.setattr(runner, "_run_winsw", fake_run_winsw)

    assert runner.get_status(config) == ("running", "Started")


def test_install_service_reinstalls_when_windows_reports_service_already_exists(monkeypatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = ServiceRunner(tmp_path / "runtime")
    calls: list[tuple[str, bool]] = []
    install_attempts = 0

    def fake_run_winsw(config: AppConfig, command: str, require_admin: bool = False):
        nonlocal install_attempts
        calls.append((command, require_admin))
        if command == "install":
            install_attempts += 1
            if install_attempts == 1:
                return ActionResult(False, "Failed to install the service. Der angegebene Dienst ist bereits vorhanden.")
        return ActionResult(True, command.title())

    monkeypatch.setattr(runner, "_run_winsw", fake_run_winsw)

    result = runner.install_service(config)

    assert result.ok is True
    assert calls == [("install", True), ("stop", False), ("uninstall", True), ("install", True)]


def test_stop_service_succeeds_when_service_is_not_installed(monkeypatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = ServiceRunner(tmp_path / "runtime")

    def fake_run_winsw(config: AppConfig, command: str, require_admin: bool = False):
        return ActionResult(False, "FATAL - The specified service does not exist as an installed service.")

    monkeypatch.setattr(runner, "_run_winsw", fake_run_winsw)

    result = runner.stop_service(config)

    assert result.ok is True
    assert result.message == "service is not installed"


def test_start_service_installs_missing_service_before_start(monkeypatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = ServiceRunner(tmp_path / "runtime")
    calls: list[tuple[str, bool]] = []

    def fake_run_winsw(config: AppConfig, command: str, require_admin: bool = False):
        calls.append((command, require_admin))
        if command == "status":
            return ActionResult(False, "FATAL - service is not installed")
        return ActionResult(True, command.title())

    monkeypatch.setattr(runner, "_run_winsw", fake_run_winsw)

    result = runner.start_service(config)

    assert result.ok is True
    assert calls == [("status", False), ("install", True), ("start", False)]


def test_start_service_reinstalls_stopped_service_before_start(monkeypatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = ServiceRunner(tmp_path / "runtime")
    calls: list[tuple[str, bool]] = []

    def fake_run_winsw(config: AppConfig, command: str, require_admin: bool = False):
        calls.append((command, require_admin))
        if command == "status":
            return ActionResult(True, "Stopped")
        return ActionResult(True, command.title())

    monkeypatch.setattr(runner, "_run_winsw", fake_run_winsw)

    result = runner.start_service(config)

    assert result.ok is True
    assert calls == [("status", False), ("uninstall", True), ("install", True), ("start", False)]


def test_stop_service_uninstalls_after_stop(monkeypatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = ServiceRunner(tmp_path / "runtime")
    calls: list[tuple[str, bool]] = []

    def fake_run_winsw(config: AppConfig, command: str, require_admin: bool = False):
        calls.append((command, require_admin))
        return ActionResult(True, command.title())

    monkeypatch.setattr(runner, "_run_winsw", fake_run_winsw)

    result = runner.stop_service(config)

    assert result.ok is True
    assert calls == [("stop", False), ("uninstall", True)]


def test_restart_service_installs_when_service_is_missing(monkeypatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = ServiceRunner(tmp_path / "runtime")
    calls: list[tuple[str, bool]] = []

    def fake_run_winsw(config: AppConfig, command: str, require_admin: bool = False):
        calls.append((command, require_admin))
        if command in {"stop", "status"}:
            return ActionResult(False, "FATAL - service is not installed")
        return ActionResult(True, command.title())

    monkeypatch.setattr(runner, "_run_winsw", fake_run_winsw)

    result = runner.restart_service(config)

    assert result.ok is True
    assert calls == [("stop", False), ("status", False), ("install", True), ("start", False)]


def test_start_service_warns_when_installed_account_differs(monkeypatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    config.service_account = r"igefa\jobserver"
    inspector = _StubInspector(
        ServiceInfo(exists=True, name="demo-service", start_name="LocalSystem", state="Running", process_id=42)
    )
    runner = ServiceRunner(tmp_path / "runtime", inspector=inspector)

    def fake_run_winsw(config: AppConfig, command: str, require_admin: bool = False):
        if command == "status":
            return ActionResult(False, "FATAL - service is not installed")
        return ActionResult(True, command.title())

    monkeypatch.setattr(runner, "_run_winsw", fake_run_winsw)

    result = runner.start_service(config)

    assert result.ok is True
    assert "WARNING" in result.message
    assert "LocalSystem" in result.message
    assert inspector.calls == ["demo-service"]


def test_start_service_does_not_warn_when_account_matches(monkeypatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    config.service_account = r"igefa\jobserver"
    inspector = _StubInspector(
        ServiceInfo(exists=True, name="demo-service", start_name=r"igefa\jobserver", state="Running", process_id=42)
    )
    runner = ServiceRunner(tmp_path / "runtime", inspector=inspector)

    def fake_run_winsw(config: AppConfig, command: str, require_admin: bool = False):
        if command == "status":
            return ActionResult(False, "FATAL - service is not installed")
        return ActionResult(True, command.title())

    monkeypatch.setattr(runner, "_run_winsw", fake_run_winsw)

    result = runner.start_service(config)

    assert result.ok is True
    assert "WARNING" not in result.message


def test_start_service_skips_verification_without_configured_account(monkeypatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    inspector = _StubInspector(ServiceInfo(exists=True, name="demo-service", start_name="LocalSystem"))
    runner = ServiceRunner(tmp_path / "runtime", inspector=inspector)

    def fake_run_winsw(config: AppConfig, command: str, require_admin: bool = False):
        if command == "status":
            return ActionResult(False, "FATAL - service is not installed")
        return ActionResult(True, command.title())

    monkeypatch.setattr(runner, "_run_winsw", fake_run_winsw)

    result = runner.start_service(config)

    assert result.ok is True
    assert "WARNING" not in result.message
    assert inspector.calls == []


def test_diagnose_reports_account_mismatch(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    config.service_account = r"igefa\jobserver"
    inspector = _StubInspector(
        ServiceInfo(
            exists=True,
            name="demo-service",
            start_name="LocalSystem",
            state="Running",
            process_id=42,
            path_name=r"C:\runtime\demo-service.exe",
        )
    )
    runner = ServiceRunner(tmp_path / "runtime", inspector=inspector)

    result = runner.diagnose(config)

    assert result.ok is False
    assert "SERVICE_START_NAME): LocalSystem" in result.message
    assert "Account match: NO" in result.message
    assert "Network access: WARNING" in result.message


def test_diagnose_reports_healthy_domain_account(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    config.service_account = r"igefa\jobserver"
    inspector = _StubInspector(
        ServiceInfo(exists=True, name="demo-service", start_name=r"igefa\jobserver", state="Running", process_id=42)
    )
    runner = ServiceRunner(tmp_path / "runtime", inspector=inspector)

    result = runner.diagnose(config)

    assert result.ok is True
    assert "Account match: yes" in result.message
    assert "WARNING" not in result.message


def test_diagnose_reports_when_service_missing(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    config.service_account = r"igefa\jobserver"
    inspector = _StubInspector(ServiceInfo(exists=False, name="demo-service"))
    runner = ServiceRunner(tmp_path / "runtime", inspector=inspector)

    result = runner.diagnose(config)

    assert result.ok is False
    assert "Installed: no" in result.message
