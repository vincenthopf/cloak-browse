from __future__ import annotations

import contextlib
import json
import os
import signal
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4

from .browser import BrowserHandle, BrowserLauncher, BrowserOptions
from .cdp import CdpClient, CdpSnapshot
from .harness import HarnessManager, HarnessState
from .models import SESSION_SCHEMA_VERSION, SessionRecord
from .paths import AppPaths, app_paths
from .process_identity import process_start_token, same_process
from .security import redact_proxy
from .session import SessionStore

CDP_HOST = "127.0.0.1"
CDP_PORT = 9333
DAEMON_NAME = "cloak"
STATUS_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class StartOptions:
    proxy: str | None
    profile: str | None
    headless: bool
    humanize: bool
    backend: str


class CloakBrowseRuntime:
    def __init__(
        self,
        paths: AppPaths | None = None,
        store: SessionStore | None = None,
        cdp_factory: Callable[[str, int], CdpClient] | None = None,
        harness_factory: Callable[[AppPaths], HarnessManager] | None = None,
        browser_launcher: BrowserLauncher | None = None,
        process_token: Callable[[int], str | None] = process_start_token,
        process_matches: Callable[[int, str | None], bool] = same_process,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] | None = None,
        stdout: TextIO = sys.stdout,
        stderr: TextIO = sys.stderr,
        install_signal_handlers: bool = True,
    ) -> None:
        self.paths = paths or app_paths()
        self.store = store or SessionStore(self.paths)
        self.cdp_factory = cdp_factory or (lambda host, port: CdpClient(host, port))
        self.harness_factory = harness_factory or HarnessManager
        self.browser_launcher = browser_launcher or BrowserLauncher()
        self.process_token = process_token
        self.process_matches = process_matches
        self.monotonic = monotonic
        self.sleep = sleep
        self.now = now or (lambda: datetime.now(UTC))
        self.stdout = stdout
        self.stderr = stderr
        self.install_signal_handlers = install_signal_handlers

    def start(self, options: StartOptions) -> int:
        read = self.store.load()
        if read.error:
            try:
                quarantined = self.store.quarantine()
            except OSError as exc:
                self._error(f"{read.error}; cannot quarantine it: {exc}")
                return 1
            self._diagnostic(
                f"{read.error}; moved it to {quarantined}"
                if quarantined
                else read.error
            )
        elif read.record is not None:
            if not self._recover_stale_session(read.record):
                return 1

        cdp = self.cdp_factory(CDP_HOST, CDP_PORT)
        collision = cdp.probe(include_tabs=False)
        if collision.listener:
            detail = collision.browser_version or collision.error or "unknown listener"
            self._error(
                f"CDP port {CDP_PORT} is already in use by {detail}; "
                "close that process before starting CloakBrowse"
            )
            return 1

        owner_started = self.process_token(os.getpid())
        if owner_started is None:
            self._error("cannot establish a safe identity for the start process")
            return 1

        timestamp = self._timestamp()
        session = SessionRecord(
            schema_version=SESSION_SCHEMA_VERSION,
            session_id=str(uuid4()),
            phase="starting",
            owner_pid=os.getpid(),
            owner_started=owner_started,
            cdp_host=CDP_HOST,
            cdp_port=CDP_PORT,
            cdp_browser_id=None,
            daemon_name=DAEMON_NAME,
            browser_version=None,
            backend=options.backend,
            mode="headless" if options.headless else "headed",
            profile=(
                str(Path(options.profile).expanduser())
                if options.profile
                else "(temporary)"
            ),
            proxy_endpoint=redact_proxy(options.proxy),
            humanize=options.humanize,
            started_at=timestamp,
            updated_at=timestamp,
        )
        try:
            self.store.clear_stop()
            self.store.write(session)
        except OSError as exc:
            self._error(f"cannot create session state: {exc}")
            return 1

        harness = self.harness_factory(self.paths)
        browser_handle: BrowserHandle | None = None
        result = 0
        try:
            print("checking stealth chromium binary...", file=self.stdout)
            binary_path = self.browser_launcher.ensure_binary()
            print(f"  binary: {binary_path}", file=self.stdout)
            launch_mode = f"{session.mode}, {session.backend} backend"
            print(
                f"launching stealth chromium ({launch_mode}, "
                f"CDP on :{session.cdp_port})...",
                file=self.stdout,
            )
            browser_handle = self.browser_launcher.launch(
                BrowserOptions(
                    cdp_port=session.cdp_port,
                    proxy=options.proxy,
                    profile=options.profile,
                    headless=options.headless,
                    humanize=options.humanize,
                    backend=options.backend,
                )
            )
            ready = cdp.wait_ready(timeout=15.0)
            if not ready.websocket_available or not ready.browser_id:
                raise RuntimeError(
                    ready.error or "CDP endpoint did not become WebSocket-ready"
                )
            session = session.with_updates(
                phase="running",
                cdp_browser_id=ready.browser_id,
                browser_version=ready.browser_version,
                updated_at=self._timestamp(),
            )
            self.store.write(session)
            print("starting browser-harness daemon...", file=self.stdout)
            daemon_start = harness.start(session, timeout=15.0)
            if not daemon_start.ok:
                raise RuntimeError(
                    f"browser-harness daemon did not start: {daemon_start.error}"
                )
            self._print_start_summary(session)
            result = self._wait_for_shutdown(session, cdp)
        except KeyboardInterrupt:
            result = 130
        except Exception as exc:
            self._error(str(exc))
            result = 1
        finally:
            shutdown_result = self._shutdown(session, browser_handle, harness, cdp)
            if result == 0 and shutdown_result != 0:
                result = shutdown_result
        return result

    def run(self, code: str, timeout: float | None) -> int:
        read = self.store.load()
        if read.error:
            self._error(read.error)
            return 1
        session = read.record
        if session is None:
            self._error("no managed session; run `cloak-browse start` first")
            return 1
        if not self._owner_alive(session):
            self._error(
                "the browser owner is not running; close the orphaned browser manually "
                "before starting a new session"
            )
            return 1
        if session.phase not in {"running", "stopping"}:
            self._error(f"session is {session.phase}; retry after startup completes")
            return 1
        cdp = self.cdp_factory(session.cdp_host, session.cdp_port)
        snapshot = cdp.probe(
            expected_browser_id=session.cdp_browser_id,
            include_tabs=False,
        )
        if not (
            snapshot.listener
            and snapshot.websocket_available
            and snapshot.owned is True
        ):
            endpoint_error = (
                "the recorded browser is unavailable or the CDP endpoint is not owned"
            )
            self._error(snapshot.error or endpoint_error)
            return 1
        harness = self.harness_factory(self.paths)
        daemon = harness.alive(session)
        if not daemon.alive:
            if daemon.error:
                self._diagnostic(f"daemon probe failed: {daemon.error}")
            print("harness daemon not running, starting...", file=self.stderr)
            started = harness.start(session, timeout=15.0)
            if not started.ok:
                self._error(f"cannot start browser-harness daemon: {started.error}")
                return 1
        result = harness.execute(session, code, timeout)
        if result == 124:
            self._error(f"run timed out after {timeout:g}s")
        return result

    def stop(self, wait_timeout: float = 10.0) -> int:
        read = self.store.load()
        if read.error:
            self._error(read.error)
            return 1
        session = read.record
        if session is None:
            print("no managed CloakBrowse session is running.", file=self.stdout)
            return 0
        if self._owner_alive(session):
            try:
                self.store.request_stop(session.session_id, self._timestamp())
            except OSError as exc:
                self._error(f"cannot request shutdown: {exc}")
                return 1
            deadline = self.monotonic() + wait_timeout
            while self.monotonic() < deadline:
                current = self.store.load()
                if current.error:
                    self._error(current.error)
                    return 1
                if current.record is None:
                    print("CloakBrowse session stopped.", file=self.stdout)
                    return 0
                if current.record.session_id != session.session_id:
                    self._error("the session changed while shutdown was in progress")
                    return 1
                if not self._owner_alive(current.record):
                    session = current.record
                    break
                self.sleep(0.1)
            else:
                self._error(
                    "the start process did not acknowledge shutdown within "
                    f"{wait_timeout:g}s"
                )
                return 1
        return self._stop_without_owner(session)

    def status(self, json_output: bool) -> int:
        report, exit_code = self._status_report()
        for diagnostic in report["diagnostics"]:
            self._diagnostic(diagnostic)
        if json_output:
            print(json.dumps(report, sort_keys=True), file=self.stdout)
        else:
            self._print_human_status(report)
        return exit_code

    def _recover_stale_session(self, session: SessionRecord) -> bool:
        cdp = self.cdp_factory(session.cdp_host, session.cdp_port)
        snapshot = cdp.probe(
            expected_browser_id=session.cdp_browser_id,
            include_tabs=False,
        )
        harness = self.harness_factory(self.paths)
        daemon = harness.alive(session)
        if self._owner_alive(session):
            self._error(
                f"a CloakBrowse session is already {session.phase} under process "
                f"{session.owner_pid}"
            )
            return False
        if daemon.error:
            self._error(f"cannot verify the recorded daemon: {daemon.error}")
            return False
        if daemon.alive:
            stopped = harness.stop(session)
            if not stopped.ok:
                self._error(f"cannot stop the recorded daemon: {stopped.error}")
                return False
        if snapshot.listener and (
            session.cdp_browser_id is None or snapshot.owned is True
        ):
            orphaned = session.with_updates(
                phase="orphaned",
                updated_at=self._timestamp(),
            )
            try:
                self.store.write(orphaned)
            except OSError as exc:
                self._diagnostic(f"cannot update orphaned session state: {exc}")
            self._error(
                "the previous start process crashed while its browser still appears "
                f"to own CDP port {session.cdp_port}; close that browser manually. "
                "CloakBrowse did not signal a PID because ownership cannot be "
                "proven safely"
            )
            return False
        try:
            self.store.clear(expected_session_id=session.session_id)
            self.store.clear_stop(session.session_id)
            harness.cleanup(session)
        except OSError as exc:
            self._error(f"cannot clear stale session state: {exc}")
            return False
        if snapshot.listener:
            self._error(
                f"CDP port {session.cdp_port} now belongs to a different process; "
                "that process was left untouched"
            )
            return False
        return True

    def _wait_for_shutdown(self, session: SessionRecord, cdp: CdpClient) -> int:
        print(file=self.stdout)
        print("press Ctrl+C or run `cloak-browse stop` to stop", file=self.stdout)
        stop_event = threading.Event()
        previous_handlers: dict[int, Any] = {}

        def request_stop(*_: Any) -> None:
            stop_event.set()

        if self.install_signal_handlers:
            for item in (signal.SIGINT, getattr(signal, "SIGTERM", None)):
                if item is None or item in previous_handlers:
                    continue
                try:
                    previous_handlers[item] = signal.getsignal(item)
                    signal.signal(item, request_stop)
                except (OSError, ValueError):
                    previous_handlers.pop(item, None)
        next_probe = self.monotonic()
        try:
            while not stop_event.wait(0.2):
                if self.store.stop_requested(session.session_id):
                    stop_event.set()
                    break
                now = self.monotonic()
                if now < next_probe:
                    continue
                next_probe = now + 1.0
                current = self.store.load()
                if current.error:
                    self._error(current.error)
                    return 1
                if (
                    current.record is None
                    or current.record.session_id != session.session_id
                ):
                    self._error("session state disappeared or was replaced")
                    return 1
                snapshot = cdp.probe(
                    expected_browser_id=session.cdp_browser_id,
                    include_tabs=False,
                )
                if not snapshot.listener:
                    self._error("the stealth browser exited unexpectedly")
                    return 1
                if snapshot.owned is not True:
                    self._error("CDP port ownership changed unexpectedly")
                    return 1
                if not snapshot.websocket_available:
                    self._error(snapshot.error or "CDP WebSocket became unavailable")
                    return 1
            try:
                self.store.write(
                    session.with_updates(
                        phase="stopping",
                        updated_at=self._timestamp(),
                    )
                )
            except OSError as exc:
                self._diagnostic(f"cannot mark session as stopping: {exc}")
            return 0
        finally:
            for item, handler in previous_handlers.items():
                with contextlib.suppress(OSError, ValueError):
                    signal.signal(item, handler)

    def _shutdown(
        self,
        session: SessionRecord,
        browser_handle: BrowserHandle | None,
        harness: HarnessManager,
        cdp: CdpClient,
    ) -> int:
        print("shutting down...", file=self.stdout)
        errors: list[str] = []
        daemon_stop = harness.stop(session)
        if not daemon_stop.ok:
            errors.append(f"daemon shutdown failed: {daemon_stop.error}")
        if browser_handle is not None:
            try:
                browser_handle.close()
            except Exception as exc:
                errors.append(f"browser shutdown failed: {exc}")
        snapshot = cdp.probe(
            expected_browser_id=session.cdp_browser_id,
            include_tabs=False,
        )
        daemon = harness.alive(session)
        if daemon.error:
            errors.append(f"daemon verification failed: {daemon.error}")
        managed_browser_remains = snapshot.listener and (
            session.cdp_browser_id is None or snapshot.owned is True
        )
        managed_daemon_remains = daemon.alive
        if managed_browser_remains or managed_daemon_remains:
            try:
                self.store.write(
                    session.with_updates(
                        phase="orphaned",
                        updated_at=self._timestamp(),
                    )
                )
            except OSError as exc:
                errors.append(f"cannot preserve orphaned session state: {exc}")
        else:
            try:
                self.store.clear(expected_session_id=session.session_id)
                self.store.clear_stop(session.session_id)
                harness.cleanup(session)
            except OSError as exc:
                errors.append(f"session cleanup failed: {exc}")
        if snapshot.listener and snapshot.owned is False:
            errors.append(
                f"CDP port {session.cdp_port} was reused by another process "
                "and was left untouched"
            )
        for error in errors:
            self._diagnostic(error)
        if errors or managed_browser_remains or managed_daemon_remains:
            self._error(
                "shutdown left managed state behind; run `cloak-browse status` "
                "for details"
            )
            return 1
        print("done.", file=self.stdout)
        return 0

    def _stop_without_owner(self, session: SessionRecord) -> int:
        cdp = self.cdp_factory(session.cdp_host, session.cdp_port)
        snapshot = cdp.probe(
            expected_browser_id=session.cdp_browser_id,
            include_tabs=False,
        )
        harness = self.harness_factory(self.paths)
        daemon = harness.alive(session)
        if daemon.error:
            self._error(f"cannot verify the recorded daemon: {daemon.error}")
            return 1
        if daemon.alive:
            stopped = harness.stop(session)
            if not stopped.ok:
                self._error(f"cannot stop the recorded daemon: {stopped.error}")
                return 1
        if snapshot.listener and (
            session.cdp_browser_id is None or snapshot.owned is True
        ):
            try:
                self.store.write(
                    session.with_updates(
                        phase="orphaned",
                        updated_at=self._timestamp(),
                    )
                )
            except OSError as exc:
                self._diagnostic(f"cannot update orphaned session state: {exc}")
            self._error(
                "the browser owner is gone but the owned browser is still running. "
                "Close that browser manually; no PID was signalled"
            )
            return 1
        try:
            self.store.clear(expected_session_id=session.session_id)
            self.store.clear_stop(session.session_id)
            harness.cleanup(session)
        except OSError as exc:
            self._error(f"cannot clear session state: {exc}")
            return 1
        if snapshot.listener:
            self._error(
                f"the managed browser is gone, but another process owns CDP port "
                f"{session.cdp_port}; that process was left untouched"
            )
            return 1
        print("stale CloakBrowse session cleaned up.", file=self.stdout)
        return 0

    def _status_report(self) -> tuple[dict[str, Any], int]:
        diagnostics: list[str] = []
        read = self.store.load()
        session = read.record
        if read.error:
            diagnostics.append(read.error)
        cdp_host = session.cdp_host if session else CDP_HOST
        cdp_port = session.cdp_port if session else CDP_PORT
        cdp = self.cdp_factory(cdp_host, cdp_port)
        snapshot = cdp.probe(
            expected_browser_id=session.cdp_browser_id if session else None,
            include_tabs=True,
        )
        if snapshot.error:
            diagnostics.append(snapshot.error)
        owner_alive: bool | None = None
        daemon = HarnessState(False, None)
        stop_requested = False
        if session is not None:
            owner_alive = self._owner_alive(session)
            daemon = self.harness_factory(self.paths).alive(session)
            if daemon.error:
                diagnostics.append(f"daemon probe failed: {daemon.error}")
            stop_requested = self.store.stop_requested(session.session_id)

        browser_state = self._browser_state(snapshot, session)
        daemon_state = (
            "unknown" if daemon.error else ("running" if daemon.alive else "stopped")
        )
        state = self._overall_state(
            session=session,
            session_error=read.error,
            owner_alive=owner_alive,
            browser_state=browser_state,
            daemon_state=daemon_state,
            stop_requested=stop_requested,
        )
        tabs = len(snapshot.tabs) if snapshot.tabs is not None else None
        report: dict[str, Any] = {
            "schema_version": STATUS_SCHEMA_VERSION,
            "healthy": state == "running",
            "state": state,
            "browser": {
                "state": browser_state,
                "owned": snapshot.owned,
                "version": snapshot.browser_version,
                "cdp_url": f"http://{cdp_host}:{cdp_port}",
                "websocket": snapshot.websocket_available,
                "tabs": tabs,
            },
            "daemon": {
                "state": daemon_state,
                "name": session.daemon_name if session else None,
            },
            "session": {
                "present": session is not None or read.error is not None,
                "valid": session is not None,
                "id": session.session_id if session else None,
                "phase": session.phase if session else None,
                "owner_alive": owner_alive,
                "started_at": session.started_at if session else None,
                "backend": session.backend if session else None,
                "mode": session.mode if session else None,
                "profile": session.profile if session else None,
                "proxy": session.proxy_endpoint if session else None,
                "humanize": session.humanize if session else None,
            },
            "diagnostics": diagnostics,
        }
        exit_code = 0 if state in {"stopped", "running", "starting", "stopping"} else 1
        return report, exit_code

    def _browser_state(
        self,
        snapshot: CdpSnapshot,
        session: SessionRecord | None,
    ) -> str:
        if not snapshot.listener:
            return "stopped"
        if session is not None and snapshot.owned is False:
            return "foreign"
        if not snapshot.http_available or not snapshot.websocket_available:
            return "unreachable"
        if session is not None and session.cdp_browser_id is None:
            return "unverified"
        return "running"

    def _overall_state(
        self,
        session: SessionRecord | None,
        session_error: str | None,
        owner_alive: bool | None,
        browser_state: str,
        daemon_state: str,
        stop_requested: bool,
    ) -> str:
        if session_error:
            return "invalid_session"
        if session is None:
            return "stopped" if browser_state == "stopped" else "foreign_endpoint"
        if stop_requested and owner_alive:
            return "stopping"
        if session.phase == "starting" and owner_alive:
            return "starting"
        if (
            session.phase == "running"
            and owner_alive
            and browser_state == "running"
            and daemon_state == "running"
        ):
            return "running"
        if not owner_alive and browser_state in {"running", "unverified"}:
            return "orphaned"
        if not owner_alive and browser_state == "stopped" and daemon_state == "stopped":
            return "stale"
        return "degraded"

    def _print_start_summary(self, session: SessionRecord) -> None:
        print(f"  browser: {session.browser_version or '?'}", file=self.stdout)
        print(f"  backend: {session.backend}", file=self.stdout)
        print(f"  CDP:     {session.cdp_url}", file=self.stdout)
        print(f"  mode:    {session.mode}", file=self.stdout)
        print(f"  harness: ready (BU_NAME={session.daemon_name})", file=self.stdout)
        print(file=self.stdout)
        print("usage:", file=self.stdout)
        print(
            "  cloak-browse run \"new_tab('https://example.com')\"",
            file=self.stdout,
        )
        print('  cloak-browse run "print(page_info())"', file=self.stdout)
        print(
            '  cloak-browse run "print(visible_text()[:2000])"',
            file=self.stdout,
        )

    def _print_human_status(self, report: dict[str, Any]) -> None:
        print(f"state:             {report['state']}", file=self.stdout)
        browser = report["browser"]
        print(f"stealth browser:   {browser['state']}", file=self.stdout)
        if browser["version"]:
            print(f"  browser:         {browser['version']}", file=self.stdout)
        print(
            f"  CDP WebSocket:   {'ok' if browser['websocket'] else 'not ready'}",
            file=self.stdout,
        )
        if browser["tabs"] is not None:
            print(f"  tabs:            {browser['tabs']}", file=self.stdout)
        daemon = report["daemon"]
        daemon_name = f" ({daemon['name']})" if daemon["name"] else ""
        print(
            f"harness daemon:    {daemon['state']}{daemon_name}",
            file=self.stdout,
        )
        session = report["session"]
        if session["present"]:
            print("session:", file=self.stdout)
            print(f"  valid:           {session['valid']}", file=self.stdout)
            if session["valid"]:
                print(f"  phase:           {session['phase']}", file=self.stdout)
                print(f"  owner alive:     {session['owner_alive']}", file=self.stdout)
                print(f"  backend:         {session['backend']}", file=self.stdout)
                print(f"  mode:            {session['mode']}", file=self.stdout)
                print(f"  profile:         {session['profile']}", file=self.stdout)
                print(f"  started:         {session['started_at']}", file=self.stdout)
                if session["proxy"]:
                    print(f"  proxy:           {session['proxy']}", file=self.stdout)

    def _owner_alive(self, session: SessionRecord) -> bool:
        return self.process_matches(session.owner_pid, session.owner_started)

    def _timestamp(self) -> str:
        return (
            self.now()
            .astimezone(UTC)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    def _diagnostic(self, message: str) -> None:
        print(f"diagnostic: {message}", file=self.stderr)

    def _error(self, message: str) -> None:
        print(f"error: {message}", file=self.stderr)
