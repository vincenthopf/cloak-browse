from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import SessionRecord
from .paths import AppPaths, ensure_private_dir


@dataclass(frozen=True)
class SessionRead:
    record: SessionRecord | None
    error: str | None


class SessionStore:
    def __init__(
        self,
        paths: AppPaths,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.paths = paths
        self.now = now

    def load(self) -> SessionRead:
        try:
            raw = self.paths.session_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            return SessionRead(None, None)
        except OSError as exc:
            return SessionRead(None, f"cannot read session file: {exc}")
        try:
            value = json.loads(raw)
            return SessionRead(SessionRecord.from_dict(value), None)
        except (json.JSONDecodeError, ValueError) as exc:
            return SessionRead(None, f"invalid session file: {exc}")

    def write(self, record: SessionRecord) -> None:
        record.validate()
        self._write_json(self.paths.session_file, record.to_dict())

    def clear(self, expected_session_id: str | None = None) -> bool:
        if expected_session_id is not None:
            current = self.load()
            if current.error or current.record is None:
                return False
            if current.record.session_id != expected_session_id:
                return False
        try:
            self.paths.session_file.unlink()
            return True
        except FileNotFoundError:
            return False

    def quarantine(self) -> Path | None:
        source = self.paths.session_file
        if not source.exists():
            return None
        ensure_private_dir(source.parent)
        suffix = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(self.now()))
        target = source.with_name(f"session.corrupt.{suffix}.json")
        counter = 1
        while target.exists():
            target = source.with_name(f"session.corrupt.{suffix}.{counter}.json")
            counter += 1
        os.replace(source, target)
        return target

    def request_stop(self, session_id: str, requested_at: str) -> None:
        self._write_json(
            self.paths.stop_file,
            {
                "schema_version": 1,
                "session_id": session_id,
                "requested_at": requested_at,
            },
        )

    def stop_requested(self, session_id: str) -> bool:
        try:
            value = json.loads(self.paths.stop_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return False
        except (OSError, json.JSONDecodeError):
            return False
        return (
            isinstance(value, dict)
            and value.get("schema_version") == 1
            and value.get("session_id") == session_id
        )

    def clear_stop(self, session_id: str | None = None) -> bool:
        if session_id is not None:
            try:
                value = json.loads(self.paths.stop_file.read_text(encoding="utf-8"))
            except (FileNotFoundError, OSError, json.JSONDecodeError):
                value = None
            if isinstance(value, dict) and value.get("session_id") != session_id:
                return False
        try:
            self.paths.stop_file.unlink()
            return True
        except FileNotFoundError:
            return False

    def _write_json(self, path: Path, value: Any) -> None:
        ensure_private_dir(path.parent)
        payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
        fd, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            text=True,
        )
        temporary = Path(temporary_name)
        try:
            if os.name != "nt":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            if os.name != "nt":
                os.chmod(path, 0o600)
                directory_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except BaseException:
            with contextlib.suppress(OSError):
                os.close(fd)
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()
            raise
