from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

SESSION_SCHEMA_VERSION = 1
SESSION_PHASES = frozenset({"starting", "running", "stopping", "orphaned"})
_DAEMON_NAME = re.compile(r"\A[A-Za-z0-9_-]{1,64}\Z")


@dataclass(frozen=True)
class SessionRecord:
    schema_version: int
    session_id: str
    phase: str
    owner_pid: int
    owner_started: str
    cdp_host: str
    cdp_port: int
    cdp_browser_id: str | None
    daemon_name: str
    browser_version: str | None
    backend: str
    mode: str
    profile: str
    proxy_endpoint: str | None
    humanize: bool
    started_at: str
    updated_at: str

    @property
    def cdp_url(self) -> str:
        return f"http://{self.cdp_host}:{self.cdp_port}"

    def with_updates(self, **changes: Any) -> SessionRecord:
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "phase": self.phase,
            "owner_pid": self.owner_pid,
            "owner_started": self.owner_started,
            "cdp_host": self.cdp_host,
            "cdp_port": self.cdp_port,
            "cdp_browser_id": self.cdp_browser_id,
            "daemon_name": self.daemon_name,
            "browser_version": self.browser_version,
            "backend": self.backend,
            "mode": self.mode,
            "profile": self.profile,
            "proxy_endpoint": self.proxy_endpoint,
            "humanize": self.humanize,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, value: Any) -> SessionRecord:
        if not isinstance(value, dict):
            raise ValueError("session root must be an object")
        record = cls(
            schema_version=_required_int(value, "schema_version"),
            session_id=_required_str(value, "session_id"),
            phase=_required_str(value, "phase"),
            owner_pid=_required_int(value, "owner_pid"),
            owner_started=_required_str(value, "owner_started"),
            cdp_host=_required_str(value, "cdp_host"),
            cdp_port=_required_int(value, "cdp_port"),
            cdp_browser_id=_optional_str(value, "cdp_browser_id"),
            daemon_name=_required_str(value, "daemon_name"),
            browser_version=_optional_str(value, "browser_version"),
            backend=_required_str(value, "backend"),
            mode=_required_str(value, "mode"),
            profile=_required_str(value, "profile"),
            proxy_endpoint=_optional_str(value, "proxy_endpoint"),
            humanize=_required_bool(value, "humanize"),
            started_at=_required_str(value, "started_at"),
            updated_at=_required_str(value, "updated_at"),
        )
        record.validate()
        return record

    def validate(self) -> None:
        if self.schema_version != SESSION_SCHEMA_VERSION:
            raise ValueError(f"unsupported session schema {self.schema_version}")
        try:
            UUID(self.session_id)
        except ValueError as exc:
            raise ValueError("session_id must be a UUID") from exc
        if self.phase not in SESSION_PHASES:
            raise ValueError(f"invalid session phase {self.phase!r}")
        if self.owner_pid <= 0 or self.owner_pid >= 1 << 31:
            raise ValueError("owner_pid is outside the supported range")
        if not self.owner_started:
            raise ValueError("owner_started is empty")
        if self.cdp_host != "127.0.0.1":
            raise ValueError("cdp_host must be 127.0.0.1")
        if not 1 <= self.cdp_port <= 65535:
            raise ValueError("cdp_port is outside the supported range")
        if not _DAEMON_NAME.match(self.daemon_name):
            raise ValueError("daemon_name contains unsupported characters")
        if self.backend not in {"patchright", "playwright"}:
            raise ValueError(f"unsupported backend {self.backend!r}")
        if self.mode not in {"headed", "headless"}:
            raise ValueError(f"unsupported mode {self.mode!r}")


def _required_str(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise ValueError(f"{key} must be a string")
    return item


def _optional_str(value: dict[str, Any], key: str) -> str | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str):
        raise ValueError(f"{key} must be a string or null")
    return item


def _required_int(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if type(item) is not int:
        raise ValueError(f"{key} must be an integer")
    return item


def _required_bool(value: dict[str, Any], key: str) -> bool:
    item = value.get(key)
    if type(item) is not bool:
        raise ValueError(f"{key} must be a boolean")
    return item
