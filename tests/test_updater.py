from __future__ import annotations

from pathlib import Path

from app_manager.core.updater import AppUpdater
from app_manager.models import ActionResult, AppConfig


def _make_config(tmp_path: Path) -> AppConfig:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    python_path = tmp_path / ".venv" / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("", encoding="utf-8")

    return AppConfig(
        id="demo",
        display_name="Demo App",
        mode="dev",
        repo_path=repo_path,
        branch="main",
        python_path=python_path,
        venv_path=tmp_path / ".venv",
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
        winsw_exe_path=tmp_path / "winsw.exe",
        autostart_prod=False,
    )


def test_updater_blocks_dirty_working_tree(monkeypatch, tmp_path: Path) -> None:
    updater = AppUpdater()
    config = _make_config(tmp_path)
    commands: list[list[str]] = []

    def fake_run(command: list[str], cwd: Path) -> ActionResult:
        commands.append(command)
        if command[:3] == ["git", "status", "--porcelain"]:
            return ActionResult(True, " M app.py")
        return ActionResult(True, "ok")

    monkeypatch.setattr(updater, "_run", fake_run)
    result = updater.update(config)

    assert result.ok is False
    assert result.message == "working tree is dirty; update aborted"
    assert commands == [["git", "status", "--porcelain"]]
