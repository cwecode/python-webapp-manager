from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Literal

RuntimeStatus = Literal["stopped", "starting", "running", "stopping", "error", "unknown"]
HealthState = Literal["disabled", "healthy", "unhealthy", "timeout", "error", "unknown"]
ActiveMode = Literal["dev", "prod", "none", "unknown"]
GitState = Literal["disabled", "current", "update_available", "dirty", "error", "unknown"]


@dataclass
class ActionResult:
    ok: bool
    message: str


@dataclass
class LastAction:
    name: str
    ok: bool
    message: str
    timestamp: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LastAction":
        timestamp = payload.get("timestamp")
        if not isinstance(timestamp, str) or not timestamp:
            timestamp = datetime.utcnow().isoformat()
        return cls(
            name=str(payload.get("name", "unknown")),
            ok=bool(payload.get("ok", False)),
            message=str(payload.get("message", "")),
            timestamp=timestamp,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AppSnapshot:
    status: RuntimeStatus
    status_detail: str
    health: HealthState
    health_detail: str
    active_mode: ActiveMode
    last_action: LastAction | None = None
    git_state: GitState = "unknown"
    git_detail: str = "not checked"
    runtime_started_at: str | None = None
