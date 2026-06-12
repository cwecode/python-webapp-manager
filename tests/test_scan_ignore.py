from __future__ import annotations

from pathlib import Path

from app_manager.models import DiscoveredApp, ScanIgnoreRule, filter_discovered_apps


def test_scan_ignore_rule_matches_service_by_service_name() -> None:
    app = DiscoveredApp(
        pid=1234,
        process_name="python",
        display_name="Demo Service",
        local_address="127.0.0.1",
        port=8080,
        executable_path=Path(r"C:\apps\demo\.venv\Scripts\python.exe"),
        service_name="demo-service",
        service_display_name="Demo Service",
        service_status="Running",
        service_path=r"C:\tools\WinSW-x64.exe",
    )

    rule = ScanIgnoreRule.from_discovered_app(app)

    assert rule.matches(app) is True


def test_scan_ignore_rule_matches_non_service_by_process_path_and_port() -> None:
    app = DiscoveredApp(
        pid=5678,
        process_name="python",
        display_name="python",
        local_address="0.0.0.0",
        port=9000,
        executable_path=Path(r"C:\apps\demo\.venv\Scripts\python.exe"),
        service_name=None,
        service_display_name=None,
        service_status=None,
        service_path=None,
    )

    rule = ScanIgnoreRule.from_discovered_app(app)

    assert rule.matches(app) is True
    assert rule.matches(
        DiscoveredApp(
            pid=5679,
            process_name="python",
            display_name="python",
            local_address="0.0.0.0",
            port=9001,
            executable_path=Path(r"C:\apps\demo\.venv\Scripts\python.exe"),
            service_name=None,
            service_display_name=None,
            service_status=None,
            service_path=None,
        )
    ) is False


def test_filter_discovered_apps_returns_visible_results_and_ignored_count() -> None:
    ignored = DiscoveredApp(
        pid=1,
        process_name="python",
        display_name="Ignored",
        local_address="127.0.0.1",
        port=8000,
        executable_path=Path(r"C:\apps\ignored\.venv\Scripts\python.exe"),
        service_name=None,
        service_display_name=None,
        service_status=None,
        service_path=None,
    )
    visible = DiscoveredApp(
        pid=2,
        process_name="python",
        display_name="Visible",
        local_address="127.0.0.1",
        port=8001,
        executable_path=Path(r"C:\apps\visible\.venv\Scripts\python.exe"),
        service_name=None,
        service_display_name=None,
        service_status=None,
        service_path=None,
    )

    results, ignored_count = filter_discovered_apps([ignored, visible], [ScanIgnoreRule.from_discovered_app(ignored)])

    assert results == [visible]
    assert ignored_count == 1
