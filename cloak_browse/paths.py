from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_cache_path


@dataclass(frozen=True)
class HarnessPaths:
    runtime_dir: Path
    tmp_dir: Path
    config_dir: Path


@dataclass(frozen=True)
class AppPaths:
    cache_dir: Path
    session_file: Path
    stop_file: Path

    def harness(self, session_id: str) -> HarnessPaths:
        runtime_dir = Path(tempfile.gettempdir()) / "cloak-browse" / session_id
        private_dir = self.cache_dir / "harness" / session_id
        return HarnessPaths(
            runtime_dir=runtime_dir,
            tmp_dir=private_dir / "tmp",
            config_dir=private_dir / "config",
        )


def app_paths(environment: Mapping[str, str] | None = None) -> AppPaths:
    env = os.environ if environment is None else environment
    override = env.get("CLOAK_BROWSE_CACHE_DIR")
    cache_dir = (
        Path(override).expanduser().resolve()
        if override
        else Path(user_cache_path("cloak-browse", appauthor=False))
    )
    return AppPaths(
        cache_dir=cache_dir,
        session_file=cache_dir / "session.json",
        stop_file=cache_dir / "stop.json",
    )


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(path, 0o700)
    return path
