from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cloak_browse.models import SESSION_SCHEMA_VERSION, SessionRecord
from cloak_browse.paths import AppPaths


@pytest.fixture
def app_paths(tmp_path):
    return AppPaths(
        cache_dir=tmp_path,
        session_file=tmp_path / "session.json",
        stop_file=tmp_path / "stop.json",
    )


@pytest.fixture
def session_record():
    return SessionRecord(
        schema_version=SESSION_SCHEMA_VERSION,
        session_id="12345678-1234-5678-1234-567812345678",
        phase="running",
        owner_pid=321,
        owner_started="linux:10",
        cdp_host="127.0.0.1",
        cdp_port=9333,
        cdp_browser_id="browser-1",
        daemon_name="cloak",
        browser_version="Chrome/145",
        backend="patchright",
        mode="headed",
        profile="(temporary)",
        proxy_endpoint="http://proxy.example:8080",
        humanize=False,
        started_at="2026-09-01T00:00:00Z",
        updated_at="2026-09-01T00:00:00Z",
    )


@pytest.fixture
def fixed_now():
    return lambda: datetime(2026, 9, 1, tzinfo=UTC)
