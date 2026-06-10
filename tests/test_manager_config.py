from __future__ import annotations

import json
from pathlib import Path

from app_manager.models import ManagerConfig


def test_manager_config_resolves_relative_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "configs" / "manager.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "apps_dir": "configs/apps",
                "runtime_dir": "runtime",
            }
        ),
        encoding="utf-8",
    )

    config = ManagerConfig.load(config_path, base_dir=tmp_path)

    assert config.apps_dir == (tmp_path / "configs" / "apps").resolve()
    assert config.runtime_dir == (tmp_path / "runtime").resolve()
