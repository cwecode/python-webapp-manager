from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from app_manager.core.service_runner import ServiceRunner
from app_manager.models import AppConfig


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
