from __future__ import annotations

import socket
import urllib.error
import urllib.request

from app_manager.models.runtime import HealthState


class HealthChecker:
    def check(self, url: str | None, timeout: float = 2.0) -> tuple[HealthState, str]:
        normalized_url = normalize_health_url(url)
        if not normalized_url:
            return "disabled", "no health URL configured"

        request = urllib.request.Request(normalized_url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = response.status
        except urllib.error.HTTPError as exc:
            if 200 <= exc.code < 400:
                return "healthy", f"HTTP {exc.code}"
            return "unhealthy", f"HTTP {exc.code}"
        except socket.timeout:
            return "timeout", "health check timed out"
        except urllib.error.URLError as exc:
            return "error", str(exc.reason)

        if 200 <= status < 400:
            return "healthy", f"HTTP {status}"
        return "unhealthy", f"HTTP {status}"


def normalize_health_url(url: str | None) -> str | None:
    if url is None:
        return None
    normalized = url.strip()
    if not normalized:
        return None
    if "://" not in normalized:
        return f"http://{normalized}"
    return normalized
