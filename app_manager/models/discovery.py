from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DiscoveredApp:
    pid: int
    process_name: str
    display_name: str
    local_address: str
    port: int
    executable_path: Path | None
    service_name: str | None
    service_display_name: str | None
    service_status: str | None
    service_path: str | None
