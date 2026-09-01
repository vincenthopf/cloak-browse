from __future__ import annotations

import io
import json

from cloak_browse.cdp import CdpSnapshot, TabInfo
from cloak_browse.harness import HarnessState
from cloak_browse.runtime import CloakBrowseRuntime
from cloak_browse.session import SessionStore


def snapshot(
    *,
    listener=False,
    websocket=False,
    owned=None,
    browser_id=None,
    version=None,
    tabs=None,
    error=None,
    http=None,
):
    return CdpSnapshot(
        listener=listener,
        http_available=listener if http is None else http,
        websocket_available=websocket,
        owned=owned,
        browser_id=browser_id,
        browser_version=version,
        tabs=tabs,
        error=error,
    )


class StaticCdp:
    def __init__(self, value):
        self.value = value

    def probe(self, **kwargs):
        return self.value


class StaticHarness:
    def __init__(self, state):
        self.state = state

    def alive(self, session):
        return self.state


def make_runtime(
    app_paths,
    cdp_value,
    harness_state=HarnessState(False, None),
    owner_alive=False,
):
    stdout = io.StringIO()
    stderr = io.StringIO()
    runtime = CloakBrowseRuntime(
        paths=app_paths,
        store=SessionStore(app_paths),
        cdp_factory=lambda host, port: StaticCdp(cdp_value),
        harness_factory=lambda paths: StaticHarness(harness_state),
        process_matches=lambda pid, token: owner_alive,
        stdout=stdout,
        stderr=stderr,
        install_signal_handlers=False,
    )
    return runtime, stdout, stderr


def test_json_status_is_exactly_one_json_value_when_stopped(app_paths):
    runtime, stdout, stderr = make_runtime(app_paths, snapshot())
    assert runtime.status(json_output=True) == 0
    raw = stdout.getvalue()
    report = json.loads(raw)
    assert raw.count("\n") == 1
    assert report["schema_version"] == 1
    assert report["state"] == "stopped"
    assert report["browser"] == {
        "state": "stopped",
        "owned": None,
        "version": None,
        "cdp_url": "http://127.0.0.1:9333",
        "websocket": False,
        "tabs": None,
    }
    assert report["daemon"] == {"state": "stopped", "name": None}
    assert report["session"]["present"] is False
    assert stderr.getvalue() == ""


def test_corrupt_status_stays_machine_readable_and_uses_stderr(app_paths):
    app_paths.session_file.write_text("{", encoding="utf-8")
    runtime, stdout, stderr = make_runtime(app_paths, snapshot())
    assert runtime.status(json_output=True) == 1
    report = json.loads(stdout.getvalue())
    assert report["state"] == "invalid_session"
    assert report["session"]["present"] is True
    assert report["session"]["valid"] is False
    assert "invalid session file" in report["diagnostics"][0]
    assert "diagnostic: invalid session file" in stderr.getvalue()


def test_fully_running_status_is_healthy(app_paths, session_record):
    SessionStore(app_paths).write(session_record)
    runtime, stdout, _ = make_runtime(
        app_paths,
        snapshot(
            listener=True,
            websocket=True,
            owned=True,
            browser_id="browser-1",
            version="Chrome/145",
            tabs=(TabInfo("one", "https://example.com"),),
        ),
        HarnessState(True, None),
        owner_alive=True,
    )
    assert runtime.status(json_output=True) == 0
    report = json.loads(stdout.getvalue())
    assert report["state"] == "running"
    assert report["healthy"] is True
    assert report["browser"]["tabs"] == 1
    assert report["session"]["owner_alive"] is True
    assert report["session"]["proxy"] == "http://proxy.example:8080"


def test_partial_states_are_stable_and_never_use_undefined_values(
    app_paths, session_record
):
    SessionStore(app_paths).write(session_record)
    runtime, stdout, _ = make_runtime(
        app_paths,
        snapshot(listener=False),
        HarnessState(True, None),
        owner_alive=True,
    )
    assert runtime.status(json_output=True) == 1
    report = json.loads(stdout.getvalue())
    assert report["state"] == "degraded"
    assert report["browser"]["tabs"] is None
    assert report["daemon"]["state"] == "running"


def test_orphaned_and_foreign_endpoints_are_distinguished(app_paths, session_record):
    SessionStore(app_paths).write(session_record)
    runtime, stdout, _ = make_runtime(
        app_paths,
        snapshot(
            listener=True,
            websocket=True,
            owned=True,
            browser_id="browser-1",
        ),
        owner_alive=False,
    )
    assert runtime.status(json_output=True) == 1
    assert json.loads(stdout.getvalue())["state"] == "orphaned"

    stdout.seek(0)
    stdout.truncate(0)
    runtime.cdp_factory = lambda host, port: StaticCdp(
        snapshot(
            listener=True,
            websocket=True,
            owned=False,
            browser_id="other",
        )
    )
    assert runtime.status(json_output=True) == 1
    report = json.loads(stdout.getvalue())
    assert report["state"] == "degraded"
    assert report["browser"]["state"] == "foreign"


def test_no_session_with_listener_is_foreign_endpoint(app_paths):
    runtime, stdout, _ = make_runtime(
        app_paths,
        snapshot(listener=True, websocket=True, browser_id="other"),
    )
    assert runtime.status(json_output=True) == 1
    report = json.loads(stdout.getvalue())
    assert report["state"] == "foreign_endpoint"
    assert report["browser"]["owned"] is None


def test_human_status_keeps_diagnostics_out_of_stdout(app_paths):
    runtime, stdout, stderr = make_runtime(
        app_paths,
        snapshot(listener=True, http=True, error="malformed endpoint"),
    )
    assert runtime.status(json_output=False) == 1
    assert stdout.getvalue().startswith("state:             foreign_endpoint")
    assert "malformed endpoint" not in stdout.getvalue()
    assert "malformed endpoint" in stderr.getvalue()
