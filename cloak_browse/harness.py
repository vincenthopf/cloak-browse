from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import SessionRecord
from .paths import AppPaths, ensure_private_dir


@dataclass(frozen=True)
class HarnessState:
    alive: bool
    error: str | None


@dataclass(frozen=True)
class HarnessResult:
    ok: bool
    error: str | None


class HarnessManager:
    def __init__(
        self,
        paths: AppPaths,
        runner: Callable[..., Any] = subprocess.run,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.paths = paths
        self.runner = runner
        self.environment = dict(os.environ if environment is None else environment)

    def alive(self, session: SessionRecord) -> HarnessState:
        script = (
            "import os\n"
            "from browser_harness.admin import daemon_alive\n"
            "raise SystemExit(0 if daemon_alive(os.environ['BU_NAME']) else 3)\n"
        )
        try:
            result = self._run(script, session, timeout=5, capture=True)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return HarnessState(False, _brief_error(exc))
        if result.returncode == 0:
            return HarnessState(True, None)
        if result.returncode == 3:
            return HarnessState(False, None)
        return HarnessState(False, self._result_error(result, session))

    def start(self, session: SessionRecord, timeout: float = 15.0) -> HarnessResult:
        script = (
            "import os\n"
            "from browser_harness.admin import ensure_daemon\n"
            "ensure_daemon("
            "wait=float(os.environ['CLOAK_BROWSE_HARNESS_WAIT']), "
            "name=os.environ['BU_NAME'], "
            "env={"
            "'BU_NAME': os.environ['BU_NAME'], "
            "'BU_CDP_URL': os.environ['BU_CDP_URL'], "
            "'BH_RUNTIME_DIR': os.environ['BH_RUNTIME_DIR'], "
            "'BH_TMP_DIR': os.environ['BH_TMP_DIR'], "
            "'BH_CONFIG_DIR': os.environ['BH_CONFIG_DIR'], "
            "'BH_UPDATE_CHECK': '0'"
            "})\n"
        )
        extra = {"CLOAK_BROWSE_HARNESS_WAIT": str(timeout)}
        try:
            result = self._run(
                script,
                session,
                timeout=timeout + 10,
                capture=True,
                extra_environment=extra,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return HarnessResult(False, _brief_error(exc))
        if result.returncode == 0:
            state = self.alive(session)
            if state.alive:
                return HarnessResult(True, None)
            return HarnessResult(
                False, state.error or "daemon did not answer its IPC ping"
            )
        return HarnessResult(False, self._result_error(result, session))

    def stop(self, session: SessionRecord) -> HarnessResult:
        script = (
            "import os\n"
            "from browser_harness.admin import restart_daemon\n"
            "restart_daemon(os.environ['BU_NAME'])\n"
        )
        try:
            result = self._run(script, session, timeout=25, capture=True)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return HarnessResult(False, _brief_error(exc))
        if result.returncode == 0:
            return HarnessResult(True, None)
        return HarnessResult(False, self._result_error(result, session))

    def execute(
        self,
        session: SessionRecord,
        code: str,
        timeout: float | None,
    ) -> int:
        command = [sys.executable, "-m", "browser_harness.run"]
        environment = self._environment(session)
        environment["BH_REQUIRE_EXISTING_DAEMON"] = "1"
        try:
            result = self.runner(
                command,
                input=code,
                text=True,
                env=environment,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return 124
        return int(result.returncode)

    def cleanup(self, session: SessionRecord) -> None:
        harness_paths = self.paths.harness(session.session_id)
        for path in (
            harness_paths.runtime_dir,
            harness_paths.tmp_dir,
            harness_paths.config_dir,
        ):
            _remove_private_tree(path, session.session_id)

    def log_tail(self, session: SessionRecord, lines: int = 5) -> str | None:
        log_path = self.paths.harness(session.session_id).tmp_dir / "bu.log"
        try:
            content = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        values = [line for line in content.splitlines() if line.strip()]
        return " | ".join(values[-lines:])[:1000] or None

    def _run(
        self,
        script: str,
        session: SessionRecord,
        timeout: float,
        capture: bool,
        extra_environment: Mapping[str, str] | None = None,
    ) -> Any:
        environment = self._environment(session)
        if extra_environment:
            environment.update(extra_environment)
        options: dict[str, Any] = {
            "env": environment,
            "timeout": timeout,
            "check": False,
            "text": True,
        }
        if capture:
            options["stdout"] = subprocess.PIPE
            options["stderr"] = subprocess.PIPE
        return self.runner([sys.executable, "-c", script], **options)

    def _environment(self, session: SessionRecord) -> dict[str, str]:
        harness_paths = self.paths.harness(session.session_id)
        for path in (
            harness_paths.runtime_dir,
            harness_paths.tmp_dir,
            harness_paths.config_dir,
        ):
            ensure_private_dir(path)
        return {
            **self.environment,
            "BU_NAME": session.daemon_name,
            "BU_CDP_URL": session.cdp_url,
            "BH_RUNTIME_DIR": str(harness_paths.runtime_dir),
            "BH_TMP_DIR": str(harness_paths.tmp_dir),
            "BH_CONFIG_DIR": str(harness_paths.config_dir),
            "BH_UPDATE_CHECK": "0",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }

    def _result_error(self, result: Any, session: SessionRecord) -> str:
        stderr = str(getattr(result, "stderr", "") or "").strip().splitlines()
        stdout = str(getattr(result, "stdout", "") or "").strip().splitlines()
        tail = self.log_tail(session)
        values = [line.strip() for line in stderr[-2:] + stdout[-1:] if line.strip()]
        if tail:
            values.append(tail)
        return " | ".join(values)[:1200] or f"process exited {result.returncode}"


def _remove_private_tree(path: Path, session_id: str) -> None:
    if session_id not in path.parts or not path.exists():
        return
    for child in sorted(
        path.rglob("*"), key=lambda item: len(item.parts), reverse=True
    ):
        with contextlib.suppress(OSError):
            child.unlink() if child.is_file() or child.is_symlink() else child.rmdir()
    with contextlib.suppress(OSError):
        path.rmdir()


def _brief_error(error: BaseException) -> str:
    text = str(error).strip()
    return text[:500] if text else error.__class__.__name__
