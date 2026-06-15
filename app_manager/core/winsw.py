from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Callable, Protocol

from app_manager.models.manager import recommended_winsw_filename

ShellRunner = Callable[[str], str]
LATEST_RELEASE_API = "https://api.github.com/repos/winsw/winsw/releases/latest"


class UrlOpener(Protocol):
    def __call__(self, url: str, timeout: float = 30.0) -> Any:
        ...


def download_winsw(target_path: Path, opener: UrlOpener = urllib.request.urlopen) -> Path:
    release = _load_latest_release(opener)
    asset_name = recommended_winsw_filename()
    download_url = _find_asset_download_url(release, asset_name)
    if download_url is None:
        raise OSError(f"WinSW release asset not found: {asset_name}")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with opener(download_url, timeout=120.0) as response:
        payload = response.read()
    if not payload:
        raise OSError("downloaded WinSW file is empty")
    target_path.write_bytes(payload)
    return target_path.resolve()


def _load_latest_release(opener: UrlOpener) -> dict[str, Any]:
    with opener(LATEST_RELEASE_API, timeout=30.0) as response:
        payload = response.read()
    loaded = json.loads(payload.decode("utf-8"))
    if not isinstance(loaded, dict):
        raise OSError("unexpected WinSW release response")
    return loaded


def _find_asset_download_url(release: dict[str, Any], asset_name: str) -> str | None:
    assets = release.get("assets", [])
    if not isinstance(assets, list):
        return None
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        if asset.get("name") == asset_name and isinstance(asset.get("browser_download_url"), str):
            return asset["browser_download_url"]
    return None


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
