from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Optional

from app_manager.core.subprocess_utils import run_capture

ShellRunner = Callable[[str], Optional[str]]

# Aliases that all refer to the LocalSystem account, used so account
# comparison treats the different spellings as equal.
_SYSTEM_ACCOUNT_ALIASES = {
    "localsystem",
    ".\\localsystem",
    "nt authority\\system",
    "system",
}

# Built-in Windows accounts that do not present a named user identity to
# remote file servers. A service running under one of these cannot reach a
# UNC share whose permissions are granted to a specific domain/server user,
# which is the classic "service runs but the share is empty" symptom.
_BUILTIN_LOCAL_ACCOUNTS = {
    "localsystem",
    "nt authority\\system",
    "system",
    "nt authority\\localservice",
    "localservice",
    "nt authority\\networkservice",
    "networkservice",
}


@dataclass(frozen=True)
class ServiceInfo:
    exists: bool
    name: str
    start_name: Optional[str] = None
    state: Optional[str] = None
    process_id: Optional[int] = None
    path_name: Optional[str] = None


class ServiceInspector:
    """Reads the real Windows SCM state for a service via WMI (Win32_Service).

    Property names (StartName, State, ProcessId, PathName) are locale
    independent, unlike the labels printed by ``sc.exe qc``.
    """

    def __init__(self, shell_runner: ShellRunner | None = None) -> None:
        self._shell_runner = shell_runner or self._run_powershell

    def inspect(self, service_name: str) -> ServiceInfo:
        output = (self._shell_runner(_query_script(service_name)) or "").lstrip("﻿").strip()
        if not output or output == "null":
            return ServiceInfo(exists=False, name=service_name)

        payload = json.loads(output)
        if not isinstance(payload, dict):
            return ServiceInfo(exists=False, name=service_name)
        return ServiceInfo(
            exists=True,
            name=str(payload.get("Name") or service_name),
            start_name=_clean(payload.get("StartName")),
            state=_clean(payload.get("State")),
            process_id=_to_optional_int(payload.get("ProcessId")),
            path_name=_clean(payload.get("PathName")),
        )

    def _run_powershell(self, script: str) -> str:
        command = (
            "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
            "$OutputEncoding = [Console]::OutputEncoding; "
            f"{script}"
        )
        result = run_capture(["powershell", "-NoProfile", "-Command", command])
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "service inspection command failed"
            raise OSError(message)
        return result.stdout


def _query_script(service_name: str) -> str:
    safe = service_name.replace("'", "''")
    return (
        f"$svc = Get-CimInstance Win32_Service -Filter \"Name='{safe}'\" -ErrorAction SilentlyContinue; "
        "if ($null -eq $svc) { 'null' } "
        "else { $svc | Select-Object Name, StartName, State, ProcessId, PathName | ConvertTo-Json -Compress }"
    )


def normalize_account(account: str | None) -> str:
    if not account:
        return ""
    text = account.strip().lower()
    if text in _SYSTEM_ACCOUNT_ALIASES:
        return "localsystem"
    if text.startswith(".\\"):
        text = text[2:]
    return text


def accounts_match(configured: str | None, actual: str | None) -> bool:
    """True when the SCM start name matches the configured account.

    An empty configured account means "let WinSW use its default", which is
    LocalSystem; that is treated as a match against a LocalSystem start name.
    """
    expected = normalize_account(configured)
    found = normalize_account(actual)
    if not expected:
        return found in {"", "localsystem"}
    return expected == found


def _is_builtin_account(account: str | None) -> bool:
    if not account or not account.strip():
        # No explicit account -> WinSW installs the service as LocalSystem.
        return True
    text = account.strip().lower()
    if text.startswith(".\\"):
        text = text[2:]
    return text in _BUILTIN_LOCAL_ACCOUNTS


def network_account_warning(account: str | None) -> str | None:
    """Warn when the (installed) account cannot reach user-restricted shares."""
    if not _is_builtin_account(account):
        return None
    label = account.strip() if account and account.strip() else "LocalSystem (default)"
    return (
        f"service account '{label}' is a built-in local account and does not present a "
        "domain/server user identity to file servers; UNC shares restricted to a specific "
        "user are unreachable. Configure a user account that has access to the share."
    )


def _clean(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_optional_int(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
