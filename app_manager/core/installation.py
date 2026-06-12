from __future__ import annotations

import shutil
from pathlib import Path

from app_manager.models import ManagerConfig


class InstallationManager:
    def __init__(self, config_path: Path, base_dir: Path) -> None:
        self.config_path = config_path
        self.base_dir = base_dir

    def load_or_default(self) -> ManagerConfig:
        if not self.config_path.exists():
            return ManagerConfig.default(self.base_dir)
        return ManagerConfig.load(self.config_path, base_dir=self.base_dir)

    def save(self, config: ManagerConfig) -> None:
        config.save(self.config_path, self.base_dir)

    def setup_required(self, config: ManagerConfig) -> bool:
        return not config.initialized or not self._marker_path(config).exists() or any(
            not path.exists()
            for path in (config.install_dir, config.runtime_dir, config.tools_dir, config.logs_dir, config.apps_dir)
        )

    def ensure_layout(self, config: ManagerConfig) -> None:
        for path in (config.apps_dir, config.install_dir, config.runtime_dir, config.tools_dir, config.logs_dir):
            path.mkdir(parents=True, exist_ok=True)
        self._marker_path(config).write_text("python-webapp-manager installed\n", encoding="utf-8")

    def uninstall_managed_assets(self, config: ManagerConfig) -> None:
        install_dir = config.install_dir.resolve()
        if install_dir.parent == install_dir:
            raise ValueError("refusing to remove filesystem root as install directory")
        for managed_path in (config.apps_dir, config.runtime_dir, config.tools_dir, config.logs_dir):
            resolved = managed_path.resolve()
            if not _is_within(resolved, install_dir):
                raise ValueError(f"managed path is outside install_dir: {resolved}")
        if install_dir.exists():
            shutil.rmtree(install_dir)

    def _marker_path(self, config: ManagerConfig) -> Path:
        return config.install_dir / ".python-webapp-manager-installed"


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
