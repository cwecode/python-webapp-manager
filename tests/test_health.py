from __future__ import annotations

import socket
import urllib.error

from app_manager.core.health import HealthChecker


class _Response:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_health_disabled_without_url() -> None:
    checker = HealthChecker()

    status, detail = checker.check(None)

    assert status == "disabled"
    assert "no health URL" in detail


def test_health_healthy(monkeypatch) -> None:
    checker = HealthChecker()

    def fake_urlopen(request, timeout):
        return _Response(200)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    status, detail = checker.check("http://127.0.0.1:8000/health")

    assert status == "healthy"
    assert detail == "HTTP 200"


def test_health_timeout(monkeypatch) -> None:
    checker = HealthChecker()

    def fake_urlopen(request, timeout):
        raise socket.timeout()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    status, detail = checker.check("http://127.0.0.1:8000/health")

    assert status == "timeout"
    assert "timed out" in detail


def test_health_unhealthy_http_error(monkeypatch) -> None:
    checker = HealthChecker()

    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            url="http://127.0.0.1:8000/health",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    status, detail = checker.check("http://127.0.0.1:8000/health")

    assert status == "unhealthy"
    assert detail == "HTTP 503"


def test_health_assumes_http_when_scheme_is_missing(monkeypatch) -> None:
    checker = HealthChecker()
    captured_urls: list[str] = []

    def fake_urlopen(request, timeout):
        captured_urls.append(request.full_url)
        return _Response(200)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    status, detail = checker.check("127.0.0.1:8000/health")

    assert status == "healthy"
    assert detail == "HTTP 200"
    assert captured_urls == ["http://127.0.0.1:8000/health"]
