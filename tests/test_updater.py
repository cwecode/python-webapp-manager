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


def test_updater_pulls_with_autostash_when_working_tree_is_dirty(monkeypatch, tmp_path: Path) -> None:
    updater = AppUpdater()
    config = _make_config(tmp_path)
    commands: list[list[str]] = []

    def fake_run(command: list[str], cwd: Path) -> ActionResult:
        commands.append(command)
        if command[:3] == ["git", "rev-parse", "--is-inside-work-tree"]:
            return ActionResult(True, "true")
        return ActionResult(True, "ok")

    monkeypatch.setattr(updater, "_run", fake_run)
    result = updater.update(config)

    assert result.ok is True
    assert result.message == "update completed"
    assert ["git", "pull", "--ff-only", "--autostash", "origin", "main"] in commands


def test_check_update_preconditions_accepts_git_working_tree(monkeypatch, tmp_path: Path) -> None:
    updater = AppUpdater()
    config = _make_config(tmp_path)

    def fake_run_capture(command: list[str], cwd: Path):
        return type("Result", (), {"returncode": 0, "stdout": "true", "stderr": ""})()

    monkeypatch.setattr("app_manager.core.updater.run_capture", fake_run_capture)

    result = updater.check_update_preconditions(config)

    assert result.ok is True
    assert result.message == "update preconditions ok"


def test_check_status_reports_update_available(monkeypatch, tmp_path: Path) -> None:
    updater = AppUpdater()
    config = _make_config(tmp_path)
    commands: list[list[str]] = []

    def fake_run(command: list[str], cwd: Path) -> ActionResult:
        commands.append(command)
        if command[:2] == ["git", "rev-parse"]:
            return ActionResult(True, "true")
        if command[:3] == ["git", "status", "--porcelain"]:
            return ActionResult(True, "")
        if command[:2] == ["git", "fetch"]:
            return ActionResult(True, "fetched")
        if command[:3] == ["git", "rev-list", "--left-right"]:
            return ActionResult(True, "0\t2")
        return ActionResult(False, "unexpected command")

    monkeypatch.setattr(updater, "_run", fake_run)

    state, detail = updater.check_status(config)

    assert state == "update_available"
    assert "2 commit(s) behind origin/main" == detail
    assert ["git", "fetch", "origin", "main", "--prune"] in commands


def test_check_status_reports_dirty_working_tree(monkeypatch, tmp_path: Path) -> None:
    updater = AppUpdater()
    config = _make_config(tmp_path)

    def fake_run(command: list[str], cwd: Path) -> ActionResult:
        if command[:2] == ["git", "rev-parse"]:
            return ActionResult(True, "true")
        if command[:3] == ["git", "status", "--porcelain"]:
            return ActionResult(True, " M app.py")
        if command[:2] == ["git", "fetch"]:
            return ActionResult(True, "fetched")
        if command[:3] == ["git", "rev-list", "--left-right"]:
            return ActionResult(True, "0\t0")
        return ActionResult(False, "unexpected command")

    monkeypatch.setattr(updater, "_run", fake_run)

    assert updater.check_status(config) == ("dirty", "working tree has local changes; up to date with origin/main")


def test_check_status_reports_update_available_even_with_local_changes(monkeypatch, tmp_path: Path) -> None:
    updater = AppUpdater()
    config = _make_config(tmp_path)

    def fake_run(command: list[str], cwd: Path) -> ActionResult:
        if command[:2] == ["git", "rev-parse"]:
            return ActionResult(True, "true")
        if command[:3] == ["git", "status", "--porcelain"]:
            return ActionResult(True, " M app.py")
        if command[:2] == ["git", "fetch"]:
            return ActionResult(True, "fetched")
        if command[:3] == ["git", "rev-list", "--left-right"]:
            return ActionResult(True, "0\t2")
        return ActionResult(False, "unexpected command")

    monkeypatch.setattr(updater, "_run", fake_run)

    assert updater.check_status(config) == (
        "update_available",
        "2 commit(s) behind origin/main; local changes will be autostashed during update",
    )


def test_check_status_caches_remote_fetch(monkeypatch, tmp_path: Path) -> None:
    updater = AppUpdater(fetch_ttl_seconds=300)
    config = _make_config(tmp_path)
    fetch_count = 0

    def fake_run(command: list[str], cwd: Path) -> ActionResult:
        nonlocal fetch_count
        if command[:2] == ["git", "rev-parse"]:
            return ActionResult(True, "true")
        if command[:3] == ["git", "status", "--porcelain"]:
            return ActionResult(True, "")
        if command[:2] == ["git", "fetch"]:
            fetch_count += 1
            return ActionResult(True, "fetched")
        if command[:3] == ["git", "rev-list", "--left-right"]:
            return ActionResult(True, "0\t0")
        return ActionResult(False, "unexpected command")

    monkeypatch.setattr(updater, "_run", fake_run)

    assert updater.check_status(config)[0] == "current"
    assert updater.check_status(config)[0] == "current"
    assert fetch_count == 1
