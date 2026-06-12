from __future__ import annotations

import json
from pathlib import Path

from app_manager.models import ManagerConfig
from app_manager.models.scan_ignore import ScanIgnoreRule
from app_manager.models.manager import recommended_winsw_filename


def test_manager_config_resolves_relative_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "configs" / "manager.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "apps_dir": "configs/apps",
                "runtime_dir": "runtime",
                "initialized": False,
            }
        ),
        encoding="utf-8",
    )

    config = ManagerConfig.load(config_path, base_dir=tmp_path)

    assert config.apps_dir == (tmp_path / "configs" / "apps").resolve()
    assert config.runtime_dir == (tmp_path / "runtime").resolve()
    assert config.install_dir == tmp_path.resolve()
    assert config.tools_dir == (tmp_path / "tools").resolve()
    assert config.logs_dir == (tmp_path / "logs").resolve()
    assert config.winsw_exe_path == (tmp_path / "tools" / "WinSW-x64.exe").resolve()


def test_manager_config_default_uses_programdata_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))

    config = ManagerConfig.default(tmp_path)

    assert config.apps_dir == config.install_dir / "apps"
    assert config.install_dir == (tmp_path / "ProgramData" / "python-webapp-manager")
    assert config.runtime_dir == config.install_dir / "runtime"
    assert config.tools_dir == config.install_dir / "tools"
    assert config.logs_dir == config.install_dir / "logs"
    assert config.winsw_exe_path == config.tools_dir / recommended_winsw_filename()
    assert config.initialized is False


def test_manager_config_loads_scan_ignore_rules(tmp_path: Path) -> None:
    config_path = tmp_path / "configs" / "manager.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "apps_dir": "configs/apps",
                "install_dir": "install",
                "winsw_exe_path": "install/tools/WinSW-x64.exe",
                "scan_ignore_rules": [
                    {
                        "label": "service:demo-service",
                        "service_name": "demo-service",
                    }
                ],
                "initialized": True,
            }
        ),
        encoding="utf-8",
    )

    config = ManagerConfig.load(config_path, base_dir=tmp_path)

    assert config.scan_ignore_rules == (ScanIgnoreRule(label="service:demo-service", service_name="demo-service"),)
