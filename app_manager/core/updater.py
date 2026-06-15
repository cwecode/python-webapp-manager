from __future__ import annotations

import subprocess
import time
from pathlib import Path

from app_manager.core.subprocess_utils import run_capture
from app_manager.models.config import AppConfig
from app_manager.models.runtime import ActionResult, GitState

GitStatus = tuple[GitState, str]


class AppUpdater:
    def __init__(self, fetch_ttl_seconds: float = 300.0) -> None:
        self.fetch_ttl_seconds = fetch_ttl_seconds
        self._last_fetch_by_repo: dict[tuple[str, str], float] = {}

    def check_status(self, config: AppConfig, *, fetch: bool = True) -> GitStatus:
        if config.mode == "observed":
            return "disabled", "observed app"
        if not config.repo_path.exists():
            return "error", f"repo path not found: {config.repo_path}"

        inside = self._run(["git", "rev-parse", "--is-inside-work-tree"], cwd=config.repo_path)
        if not inside.ok or inside.message.strip().lower() != "true":
            return "error", "repo path is not a git working tree"

        dirty = self._run(["git", "status", "--porcelain"], cwd=config.repo_path)
        if not dirty.ok:
            return "error", dirty.message
        if dirty.message.strip():
            return "dirty", "working tree has local changes"

        if fetch and self._should_fetch(config):
            fetched = self._run(["git", "fetch", "origin", config.branch, "--prune"], cwd=config.repo_path)
            if not fetched.ok:
                return "error", fetched.message
            self._mark_fetched(config)

        upstream = f"origin/{config.branch}"
        counts = self._run(["git", "rev-list", "--left-right", "--count", f"HEAD...{upstream}"], cwd=config.repo_path)
        if not counts.ok:
            return "error", counts.message

        parts = counts.message.split()
        if len(parts) < 2:
            return "unknown", counts.message or "could not compare with remote"
        try:
            ahead, behind = int(parts[0]), int(parts[1])
        except ValueError:
            return "unknown", counts.message or "could not compare with remote"
        if behind > 0:
            return "update_available", f"{behind} commit(s) behind {upstream}"
        if ahead > 0:
            return "current", f"{ahead} local commit(s) ahead of {upstream}"
        return "current", f"up to date with {upstream}"

    def _should_fetch(self, config: AppConfig) -> bool:
        last_fetch = self._last_fetch_by_repo.get(self._fetch_key(config))
        return last_fetch is None or time.monotonic() - last_fetch >= self.fetch_ttl_seconds

    def _mark_fetched(self, config: AppConfig) -> None:
        self._last_fetch_by_repo[self._fetch_key(config)] = time.monotonic()

    def _fetch_key(self, config: AppConfig) -> tuple[str, str]:
        return str(config.repo_path.resolve()), config.branch

    def update(self, config: AppConfig) -> ActionResult:
        if not config.repo_path.exists():
            return ActionResult(False, f"repo path not found: {config.repo_path}")
        if not config.python_path.exists():
            return ActionResult(False, f"python path not found: {config.python_path}")

        dirty = self._run(["git", "status", "--porcelain"], cwd=config.repo_path)
        if not dirty.ok:
            return dirty
        if dirty.message.strip():
            return ActionResult(False, "working tree is dirty; update aborted")

        steps = [
            ["git", "fetch", "--all", "--prune"],
            ["git", "checkout", config.branch],
            ["git", "pull", "--ff-only", "origin", config.branch],
        ]
        for step in steps:
            result = self._run(step, cwd=config.repo_path)
            if not result.ok:
                return result

        requirements_file = config.requirements_file or (config.repo_path / "requirements.txt")
        if requirements_file.exists():
            result = self._run(
                [str(config.python_path), "-m", "pip", "install", "-r", str(requirements_file)],
                cwd=config.repo_path,
            )
            if not result.ok:
                return result

        if config.init_command:
            result = run_capture(
                config.init_command,
                cwd=config.repo_path,
                shell=True,
            )
            message = result.stdout.strip() or result.stderr.strip() or "init command finished"
            if result.returncode != 0:
                return ActionResult(False, message)

        return ActionResult(True, "update completed")

    def _run(self, command: list[str], cwd: Path) -> ActionResult:
        result = run_capture(
            command,
            cwd=cwd,
        )
        message = result.stdout.strip() or result.stderr.strip() or "command completed"
        return ActionResult(result.returncode == 0, message)
