from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app_manager.core.runtime_store import RuntimeStore
from app_manager.core.subprocess_utils import run_capture
from app_manager.models.config import AppConfig
from app_manager.models.runtime import ActionResult, RuntimeStatus


class ProcessRunner:
    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = runtime_root
        self.store = RuntimeStore(runtime_root)

    def start_dev(self, config: AppConfig) -> ActionResult:
        if config.mode == "prod":
            return ActionResult(False, "app does not support dev mode")
        if config.mode == "observed":
            return ActionResult(False, "observed apps cannot be started")

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

    def attach_dev_process(self, config: AppConfig, pid: int, command: list[str] | None = None) -> ActionResult:
        if config.mode in {"prod", "observed"}:
            return ActionResult(False, "app does not support dev mode")
        if pid <= 0:
            return ActionResult(False, "PID must be a positive integer")
        if not self._pid_running(pid):
            return ActionResult(False, f"PID {pid} is not running")

        runtime_dir = self.store.app_dir(config)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "pid": pid,
            "command": command or [],
            "started_at": datetime.now(timezone.utc).isoformat(),
            "attached": True,
        }
        self.store.dev_state_path(config).write_text(json.dumps(state, indent=2), encoding="utf-8")
        return ActionResult(True, f"attached running PID {pid}")

    def stop_dev(self, config: AppConfig) -> ActionResult:
        state_path = self.store.dev_state_path(config)
        if not state_path.exists():
            return ActionResult(False, "no dev state file found")

        state = self._read_state(state_path)
        pid = state["pid"]
        if not self._pid_running(pid):
            state_path.unlink(missing_ok=True)
            return ActionResult(True, f"PID {pid} already stopped")

        graceful = run_capture(
            ["taskkill", "/PID", str(pid), "/T"],
        )
        if graceful.returncode != 0 and self._pid_running(pid):
            forced = run_capture(
                ["taskkill", "/F", "/PID", str(pid), "/T"],
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

    def stop_listening_process(self, config: AppConfig) -> ActionResult:
        pid = self.find_listening_pid(config)
        if pid is None:
            return ActionResult(False, f"no listening process found on {config.host}:{config.port}")
        if pid <= 4:
            return ActionResult(False, f"refusing to stop system PID {pid}")

        result = run_capture(["taskkill", "/F", "/PID", str(pid), "/T"])
        if result.returncode != 0:
            return ActionResult(False, result.stderr.strip() or result.stdout.strip() or f"failed to stop PID {pid}")
        return ActionResult(True, f"force stopped external PID {pid}")

    def get_status(self, config: AppConfig) -> tuple[RuntimeStatus, str]:
        if config.mode == "observed":
            return "unknown", "observed apps are not process-managed"

        state_path = self.store.dev_state_path(config)
        if not state_path.exists():
            return "stopped", "no dev process tracked"

        state = self._read_state(state_path)
        pid = state["pid"]
        if self._pid_running(pid):
            if state.get("attached"):
                return "running", f"attached PID {pid}"
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
        result = run_capture(
            ["tasklist", "/FI", f"PID eq {pid}"],
        )
        return result.returncode == 0 and str(pid) in result.stdout

    def find_listening_pid(self, config: AppConfig) -> int | None:
        records = self._load_tcp_listeners(config.port)
        for record in records:
            pid = _to_int(record.get("OwningProcess"))
            address = str(record.get("LocalAddress", "")).strip()
            if pid > 0 and _address_matches(config.host, address):
                return pid
        return None

    def _load_tcp_listeners(self, port: int) -> list[dict[str, object]]:
        script = (
            f"$port = {port}; "
            "Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | "
            "Select-Object LocalAddress, LocalPort, OwningProcess | "
            "ConvertTo-Json -Compress"
        )
        command = (
            "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
            "$OutputEncoding = [Console]::OutputEncoding; "
            f"{script}"
        )
        result = run_capture(["powershell", "-NoProfile", "-Command", command])
        if result.returncode != 0 or not result.stdout.strip():
            return []
        try:
            payload = json.loads(result.stdout.lstrip("\ufeff"))
        except json.JSONDecodeError:
            return []
        if payload is None:
            return []
        if isinstance(payload, dict):
            return [payload]
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []


def _to_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _address_matches(config_host: str, listener_address: str) -> bool:
    host = config_host.strip().lower()
    address = listener_address.strip().lower()
    if host in {"0.0.0.0", "::"}:
        return True
    if host in {"127.0.0.1", "localhost", "::1"}:
        return address in {"127.0.0.1", "localhost", "::1", "0.0.0.0", "::"}
    return address == host or address in {"0.0.0.0", "::"}
