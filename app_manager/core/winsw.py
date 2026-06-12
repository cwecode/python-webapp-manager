from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable

from app_manager.models.manager import recommended_winsw_filename

ShellRunner = Callable[[str], str]


class WinSWDetector:
    def __init__(self, shell_runner: ShellRunner | None = None, env: dict[str, str] | None = None) -> None:
        self._shell_runner = shell_runner or self._run_powershell
        self._env = env or os.environ

    def discover(self, install_dir: Path) -> list[Path]:
        candidates: list[Path] = []
        preferred_names = {recommended_winsw_filename().lower(), "winsw-x64.exe", "winsw-x86.exe", "winsw.exe"}

        for candidate in self._direct_candidates(install_dir):
            if candidate.exists():
                candidates.append(candidate.resolve())

        for raw_path in self._load_paths_from_shell(install_dir):
            path = Path(raw_path)
            if path.name.lower() not in preferred_names:
                continue
            candidates.append(path.resolve())

        unique: dict[str, Path] = {}
        for candidate in candidates:
            unique[str(candidate).lower()] = candidate
        return sorted(unique.values(), key=lambda item: (0 if _is_within(item, install_dir) else 1, str(item).lower()))

    def _direct_candidates(self, install_dir: Path) -> list[Path]:
        candidate_roots = [
            install_dir / "tools" / recommended_winsw_filename(),
            install_dir / "tools" / "WinSW-x64.exe",
            install_dir / "tools" / "WinSW-x86.exe",
            install_dir / "tools" / "winsw.exe",
            Path(self._env.get("PROGRAMDATA", r"C:\ProgramData")) / "python-webapp-manager" / "tools" / recommended_winsw_filename(),
            Path(r"C:\tools") / recommended_winsw_filename(),
            Path(r"C:\tools") / "WinSW-x64.exe",
            Path(r"C:\tools") / "WinSW-x86.exe",
        ]
        return candidate_roots

    def _load_paths_from_shell(self, install_dir: Path) -> list[str]:
        output = (self._shell_runner(_discovery_script(install_dir, self._env)) or "").lstrip("\ufeff").strip()
        if not output:
            return []

        payload = json.loads(output)
        if payload is None:
            return []
        if isinstance(payload, str):
            return [payload]
        if isinstance(payload, list):
            return [str(item).strip() for item in payload if str(item).strip()]
        raise ValueError("expected JSON string or array from WinSW discovery command")

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
            message = stderr.strip() or stdout.strip() or "WinSW discovery command failed"
            raise OSError(message)
        return stdout


def _discovery_script(install_dir: Path, env: dict[str, str]) -> str:
    roots = [
        install_dir / "tools",
        Path(env.get("PROGRAMDATA", r"C:\ProgramData")) / "python-webapp-manager" / "tools",
        Path(r"C:\tools"),
    ]
    if env.get("ProgramFiles"):
        roots.append(Path(env["ProgramFiles"]))
    if env.get("ProgramFiles(x86)"):
        roots.append(Path(env["ProgramFiles(x86)"]))

    roots_literal = ", ".join(f"'{str(root)}'" for root in roots)
    return f"""
$results = New-Object System.Collections.Generic.List[string]
$roots = @({roots_literal})
foreach ($root in $roots) {{
    if ($root -and (Test-Path $root)) {{
        Get-ChildItem -Path $root -Recurse -File -Filter *winsw*.exe -ErrorAction SilentlyContinue |
            ForEach-Object {{ [void]$results.Add($_.FullName) }}
    }}
}}

Get-Command *winsw*.exe -ErrorAction SilentlyContinue |
    ForEach-Object {{
        if ($_.Source) {{ [void]$results.Add($_.Source) }}
    }}

Get-CimInstance Win32_Service -ErrorAction SilentlyContinue |
    ForEach-Object {{
        $path = $_.PathName
        if ($path) {{
            $match = [regex]::Match($path, '(?i)[A-Z]:\\\\[^"]*winsw[^"]*\\.exe|[A-Z]:\\\\[^ ]*winsw[^ ]*\\.exe')
            if ($match.Success) {{ [void]$results.Add($match.Value.Trim('"')) }}
        }}
    }}

$results | Sort-Object -Unique | ConvertTo-Json -Compress
""".strip()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
