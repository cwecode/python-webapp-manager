from __future__ import annotations

import subprocess
from pathlib import Path

from app_manager.models.config import AppConfig
from app_manager.models.runtime import ActionResult


class AppUpdater:
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
            result = subprocess.run(
                config.init_command,
                cwd=config.repo_path,
                capture_output=True,
                text=True,
                shell=True,
                check=False,
            )
            message = result.stdout.strip() or result.stderr.strip() or "init command finished"
            if result.returncode != 0:
                return ActionResult(False, message)

        return ActionResult(True, "update completed")

    def _run(self, command: list[str], cwd: Path) -> ActionResult:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        message = result.stdout.strip() or result.stderr.strip() or "command completed"
        return ActionResult(result.returncode == 0, message)
