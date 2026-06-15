from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

from app_manager.models import DiscoveredApp

ShellRunner = Callable[[str], Optional[str]]

_LISTENERS_SCRIPT = """
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
Select-Object LocalAddress, LocalPort, OwningProcess |
ConvertTo-Json -Compress
""".strip()

_PROCESSES_SCRIPT = """
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
ForEach-Object {
    $owner = $null
    try {
        $ownerResult = Invoke-CimMethod -InputObject $_ -MethodName GetOwner -ErrorAction SilentlyContinue
        if ($ownerResult.User) {
            if ($ownerResult.Domain) {
                $owner = "$($ownerResult.Domain)\\$($ownerResult.User)"
            } else {
                $owner = $ownerResult.User
            }
        }
    } catch {
        $owner = $null
    }

    [pscustomobject]@{
        Id = $_.ProcessId
        ProcessName = [System.IO.Path]::GetFileNameWithoutExtension($_.Name)
        Path = $_.ExecutablePath
        ParentProcessId = $_.ParentProcessId
        Owner = $owner
    }
} |
ConvertTo-Json -Compress
""".strip()

_SERVICES_SCRIPT = """
Get-CimInstance Win32_Service -ErrorAction SilentlyContinue |
Select-Object Name, DisplayName, State, ProcessId, PathName |
ConvertTo-Json -Compress
""".strip()


class WindowsAppDiscovery:
    def __init__(
        self,
        shell_runner: ShellRunner | None = None,
        default_winsw_path: Path | None = None,
        default_logs_root: Path | None = None,
    ) -> None:
        self._shell_runner = shell_runner or self._run_powershell
        self._default_winsw_path = default_winsw_path or Path(r"tools\WinSW-x64.exe")
        self._default_logs_root = default_logs_root or Path("logs")

    def discover(self) -> list[DiscoveredApp]:
        listeners = self._load_records(_LISTENERS_SCRIPT)
        processes = self._index_by_int(self._load_records(_PROCESSES_SCRIPT), "Id")
        services = self._index_services(self._load_records(_SERVICES_SCRIPT))

        discovered: list[DiscoveredApp] = []
        seen: set[tuple[int, str, int]] = set()

        for listener in listeners:
            pid = _to_int(listener.get("OwningProcess"))
            port = _to_int(listener.get("LocalPort"))
            address = str(listener.get("LocalAddress", "")).strip()
            if pid <= 4 or port <= 0 or not address:
                continue

            key = (pid, address, port)
            if key in seen:
                continue
            seen.add(key)

            process = processes.get(pid, {})
            process_name = str(process.get("ProcessName") or f"pid-{pid}")
            executable_path = _to_path(process.get("Path"))
            service = _match_service(services.get(pid, []), executable_path)
            display_name = (
                str(service.get("DisplayName")).strip()
                if service.get("DisplayName")
                else process_name
            )

            discovered.append(
                DiscoveredApp(
                    pid=pid,
                    process_name=process_name,
                    display_name=display_name,
                    local_address=address,
                    port=port,
                    executable_path=executable_path,
                    service_name=_to_optional_str(service.get("Name")),
                    service_display_name=_to_optional_str(service.get("DisplayName")),
                    service_status=_to_optional_str(service.get("State")),
                    service_path=_extract_executable(_to_optional_str(service.get("PathName"))),
                    owner=_to_optional_str(process.get("Owner")),
                    parent_pid=_to_optional_int(process.get("ParentProcessId")),
                )
            )

        return sorted(discovered, key=lambda item: (item.display_name.lower(), item.port, item.pid))

    def suggest_config(self, app: DiscoveredApp) -> dict[str, Any]:
        slug = _slugify(app.service_name or app.display_name or app.process_name)
        executable_name = app.executable_path.name.lower() if app.executable_path else ""
        winsw_backed = _is_winsw_executable(app.service_path)

        repo_path = "."
        python_path = r".venv\Scripts\python.exe"
        venv_path = r".venv"
        entry_kind = "uvicorn"
        entry_target = "main:app"

        if executable_name == "python.exe" and app.executable_path is not None:
            python_path = str(app.executable_path)
            venv_path = str(app.executable_path.parent.parent)
            repo_path = str(app.executable_path.parent.parent.parent)
        elif executable_name.startswith("waitress-serve") and app.executable_path is not None:
            venv_root = app.executable_path.parent.parent
            python_path = str(venv_root / "Scripts" / "python.exe")
            venv_path = str(venv_root)
            repo_path = str(venv_root.parent)
            entry_kind = "waitress"
            entry_target = "wsgi:app"
        elif app.executable_path is not None:
            repo_path = str(app.executable_path.parent)

        winsw_path = app.service_path if winsw_backed else str(self._default_winsw_path)

        return {
            "id": slug,
            "display_name": app.service_display_name or app.display_name,
            "mode": "prod" if winsw_backed else "dev",
            "repo_path": repo_path,
            "branch": "main",
            "python_path": python_path,
            "venv_path": venv_path,
            "entry_kind": entry_kind,
            "entry_target": entry_target,
            "host": app.local_address,
            "port": app.port,
            "health_url": None,
            "env_file": None,
            "requirements_file": None,
            "init_command": None,
            "service_name": app.service_name or slug,
            "log_dir": str(self._default_logs_root / slug),
            "winsw_exe_path": winsw_path,
            "autostart_prod": winsw_backed,
        }

    def _load_records(self, script: str) -> list[dict[str, Any]]:
        output = (self._shell_runner(script) or "").lstrip("\ufeff").strip()
        if not output:
            return []

        payload = json.loads(output)
        if payload is None:
            return []
        if isinstance(payload, dict):
            return [payload]
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        raise ValueError("expected JSON object or array from discovery command")

    def _index_by_int(self, records: list[dict[str, Any]], field_name: str) -> dict[int, dict[str, Any]]:
        indexed: dict[int, dict[str, Any]] = {}
        for record in records:
            key = _to_int(record.get(field_name))
            if key > 0:
                indexed[key] = record
        return indexed

    def _index_services(self, records: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
        indexed: dict[int, list[dict[str, Any]]] = {}
        for record in records:
            pid = _to_int(record.get("ProcessId"))
            if pid <= 0:
                continue
            indexed.setdefault(pid, []).append(record)
        return indexed

    def _run_powershell(self, script: str) -> str:
        command = (
            "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
            "$OutputEncoding = [Console]::OutputEncoding; "
            f"{script}"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=False,
            check=False,
        )
        stdout = (result.stdout or b"").decode("utf-8", errors="replace")
        stderr = (result.stderr or b"").decode("utf-8", errors="replace")
        if result.returncode != 0:
            message = stderr.strip() or stdout.strip() or "discovery command failed"
            raise OSError(message)
        return stdout


def _match_service(services: list[dict[str, Any]], executable_path: Path | None) -> dict[str, Any]:
    if not services:
        return {}
    if executable_path is None:
        return services[0]

    executable = str(executable_path).lower()
    for service in services:
        service_executable = _extract_executable(_to_optional_str(service.get("PathName")))
        if service_executable and service_executable.lower() == executable:
            return service
    return services[0]


def _extract_executable(command_line: str | None) -> str | None:
    if not command_line:
        return None
    value = command_line.strip()
    if not value:
        return None
    if value.startswith('"'):
        closing_quote = value.find('"', 1)
        if closing_quote > 1:
            return value[1:closing_quote]
    return value.split(" ", 1)[0]


def _slugify(value: str) -> str:
    collapsed = "".join(char.lower() if char.isalnum() else "-" for char in value)
    parts = [part for part in collapsed.split("-") if part]
    return "-".join(parts) or "discovered-app"


def _is_winsw_executable(path: str | None) -> bool:
    if not path:
        return False
    return "winsw" in Path(path).name.lower()


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_optional_int(value: Any) -> int | None:
    result = _to_int(value)
    return result if result > 0 else None


def _to_path(value: Any) -> Path | None:
    text = _to_optional_str(value)
    if not text:
        return None
    return Path(text)


def _to_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
