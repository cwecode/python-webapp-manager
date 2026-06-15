from __future__ import annotations

import json
from pathlib import Path

from app_manager.core.winsw import WinSWDetector, download_winsw
from app_manager.models.manager import recommended_winsw_filename


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def test_winsw_detector_prefers_install_root_candidates(tmp_path: Path) -> None:
    install_dir = tmp_path / "python-webapp-manager"
    managed_winsw = install_dir / "tools" / "WinSW-x64.exe"
    managed_winsw.parent.mkdir(parents=True)
    managed_winsw.write_text("", encoding="utf-8")

    outputs = json.dumps(
        [
            str(tmp_path / "other" / "WinSW-x64.exe"),
            str(managed_winsw),
        ]
    )
    detector = WinSWDetector(shell_runner=lambda script: outputs, env={"PROGRAMDATA": str(tmp_path / "ProgramData")})

    result = detector.discover(install_dir)

    assert result[0] == managed_winsw.resolve()


def test_winsw_detector_collects_shell_results_and_deduplicates(tmp_path: Path) -> None:
    install_dir = tmp_path / "python-webapp-manager"
    winsw_path = tmp_path / "tools" / "WinSW-x64.exe"
    payload = json.dumps([str(winsw_path), str(winsw_path)])
    detector = WinSWDetector(shell_runner=lambda script: payload, env={"PROGRAMDATA": str(tmp_path / "ProgramData")})

    result = detector.discover(install_dir)

    assert result == [winsw_path.resolve()]


def test_winsw_detector_handles_empty_shell_output(tmp_path: Path) -> None:
    detector = WinSWDetector(shell_runner=lambda script: "", env={"PROGRAMDATA": str(tmp_path / "ProgramData")})

    assert detector.discover(tmp_path / "python-webapp-manager") == []


def test_download_winsw_uses_latest_release_asset(tmp_path: Path) -> None:
    asset_name = recommended_winsw_filename()
    calls: list[str] = []

    def opener(url: str, timeout: float = 30.0) -> _FakeResponse:
        calls.append(url)
        if url.endswith("/releases/latest"):
            return _FakeResponse(
                json.dumps(
                    {
                        "assets": [
                            {
                                "name": asset_name,
                                "browser_download_url": "https://example.invalid/winsw.exe",
                            }
                        ]
                    }
                ).encode("utf-8")
            )
        return _FakeResponse(b"binary")

    target_path = tmp_path / "tools" / asset_name

    result = download_winsw(target_path, opener=opener)

    assert result == target_path.resolve()
    assert target_path.read_bytes() == b"binary"
    assert calls == [
        "https://api.github.com/repos/winsw/winsw/releases/latest",
        "https://example.invalid/winsw.exe",
    ]
