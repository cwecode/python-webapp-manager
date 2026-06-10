from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app_manager.core.runtime_store import RuntimeStore
from app_manager.models.config import AppConfig
from app_manager.models.runtime import ActionResult, RuntimeStatus


class ProcessRunner:
    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = runtime_root
        self.store = RuntimeStore(runtime_root)

    def start_dev(self, config: AppConfig) -> ActionResult:
        if config.mode == "prod":
            return ActionResult(False, "app does not support dev mode")

        state_path = self.store.dev_state_path(config)
        if state_path.exists():
            state = self._read_state(state_path)
            if self._pid_running(state["pid"]):
                return ActionResult(False, f"process already running with PID {state['pid']}")

        runtime_dir = self.store.app_dir(config)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        config.log_dir.mkdir(parents=True, exist_ok=True)

        stdout_path = config.log_dir / "stdout.log"
        stderr_path = config.log_dir / "stderr.log"
        command = self.build_start_command(config)
        env = self._build_env(config)

        with stdout_path.open("ab") as stdout_handle, stderr_path.open("ab") as stderr_handle:
            process = subprocess.Popen(
                command,
                cwd=config.repo_path,
                env=env,
                stdout=stdout_handle,
                stderr=stderr_handle,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

        state = {
            "pid": process.pid,
            "command": command,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        return ActionResult(True, f"started PID {process.pid}")

    def stop_dev(self, config: AppConfig) -> ActionResult:
        state_path = self.store.dev_state_path(config)
        if not state_path.exists():
            return ActionResult(False, "no dev state file found")

        state = self._read_state(state_path)
        pid = state["pid"]
        if not self._pid_running(pid):
            state_path.unlink(missing_ok=True)
            return ActionResult(True, f"PID {pid} already stopped")

        graceful = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T"],
            capture_output=True,
            text=True,
            check=False,
        )
        if graceful.returncode != 0 and self._pid_running(pid):
            forced = subprocess.run(
                ["taskkill", "/F", "/PID", str(pid), "/T"],
                capture_output=True,
                text=True,
                check=False,
            )
            if forced.returncode != 0:
                return ActionResult(False, forced.stderr.strip() or forced.stdout.strip() or "failed to stop process")

        state_path.unlink(missing_ok=True)
        return ActionResult(True, f"stopped PID {pid}")

    def restart_dev(self, config: AppConfig) -> ActionResult:
        stop_result = self.stop_dev(config)
        if not stop_result.ok and "already stopped" not in stop_result.message and "no dev state" not in stop_result.message:
            return stop_result
        return self.start_dev(config)

    def get_status(self, config: AppConfig) -> tuple[RuntimeStatus, str]:
        state_path = self.store.dev_state_path(config)
        if not state_path.exists():
            return "stopped", "no dev process tracked"

        state = self._read_state(state_path)
        pid = state["pid"]
        if self._pid_running(pid):
            return "running", f"PID {pid}"

        return "error", f"state file exists but PID {pid} is not running"

    def build_start_command(self, config: AppConfig) -> list[str]:
        if config.entry_kind == "uvicorn":
            return [
                str(config.python_path),
                "-m",
                "uvicorn",
                config.entry_target,
                "--host",
                config.host,
                "--port",
                str(config.port),
            ]

        waitress_exe = config.venv_path / "Scripts" / "waitress-serve.exe"
        executable = str(waitress_exe) if waitress_exe.exists() else "waitress-serve"
        return [
            executable,
            "--host",
            config.host,
            "--port",
            str(config.port),
            config.entry_target,
        ]

    def read_log(self, config: AppConfig, stream: str) -> str:
        log_path = config.log_dir / f"{stream}.log"
        if not log_path.exists():
            return ""
        return log_path.read_text(encoding="utf-8", errors="replace")

    def _build_env(self, config: AppConfig) -> dict[str, str]:
        env = os.environ.copy()
        if config.env_file and config.env_file.exists():
            for line in config.env_file.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                env[key.strip()] = value.strip()
        return env

    def _read_state(self, state_path: Path) -> dict[str, object]:
        return json.loads(state_path.read_text(encoding="utf-8"))

    def _pid_running(self, pid: int) -> bool:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0 and str(pid) in result.stdout
