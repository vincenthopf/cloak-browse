from __future__ import annotations

import io

from cloak_browse.cdp import CdpSnapshot
from cloak_browse.harness import HarnessResult, HarnessState
from cloak_browse.runtime import CloakBrowseRuntime, StartOptions
from cloak_browse.session import SessionStore


def stopped_snapshot():
    return CdpSnapshot(False, False, False, None, None, None, None, None)


def running_snapshot(owned=True, browser_id="browser-1"):
    return CdpSnapshot(
        True,
        True,
        True,
        owned,
        browser_id,
        "Chrome/145",
        (),
        None,
    )


class SequenceCdp:
    def __init__(self, probes, ready=None):
        self.probes = list(probes)
        self.ready = ready or running_snapshot()
        self.calls = []

    def probe(self, **kwargs):
        self.calls.append(("probe", kwargs))
        if len(self.probes) > 1:
            return self.probes.pop(0)
        return self.probes[0]

    def wait_ready(self, timeout):
        self.calls.append(("wait_ready", timeout))
        return self.ready


class FakeHandle:
    def __init__(self, error=None):
        self.error = error
        self.closed = False

    def close(self):
        self.closed = True
        if self.error:
            raise self.error


class FakeBrowserLauncher:
    def __init__(self, handle=None, launch_error=None):
        self.handle = handle or FakeHandle()
        self.launch_error = launch_error
        self.ensure_calls = 0
        self.launch_options = []

    def ensure_binary(self):
        self.ensure_calls += 1
        return "/cache/cloakbrowser"

    def launch(self, options):
        self.launch_options.append(options)
        if self.launch_error:
            raise self.launch_error
        return self.handle


class FakeHarness:
    def __init__(
        self,
        alive_states=None,
        start_result=None,
        stop_result=None,
        execute_result=0,
    ):
        self.alive_states = list(alive_states or [HarnessState(False, None)])
        self.start_result = (
            HarnessResult(True, None) if start_result is None else start_result
        )
        self.stop_result = (
            HarnessResult(True, None) if stop_result is None else stop_result
        )
        self.execute_result = execute_result
        self.start_calls = []
        self.stop_calls = []
        self.execute_calls = []
        self.cleanup_calls = []

    def alive(self, session):
        if len(self.alive_states) > 1:
            return self.alive_states.pop(0)
        return self.alive_states[0]

    def start(self, session, timeout=15.0):
        self.start_calls.append((session, timeout))
        return self.start_result

    def stop(self, session):
        self.stop_calls.append(session)
        return self.stop_result

    def execute(self, session, code, timeout):
        self.execute_calls.append((session, code, timeout))
        return self.execute_result

    def cleanup(self, session):
        self.cleanup_calls.append(session)


class RecordingStore(SessionStore):
    def __init__(self, paths):
        super().__init__(paths)
        self.writes = []
        self.stop_requests = []

    def write(self, record):
        self.writes.append(record)
        super().write(record)

    def request_stop(self, session_id, requested_at):
        self.stop_requests.append((session_id, requested_at))
        super().request_stop(session_id, requested_at)


def make_runtime(
    app_paths,
    cdp,
    harness,
    browser=None,
    store=None,
    owner_alive=True,
    stdout=None,
    stderr=None,
    sleep=lambda value: None,
    monotonic=None,
):
    values = iter([0.0, 0.1, 0.2, 20.0])
    return CloakBrowseRuntime(
        paths=app_paths,
        store=store or SessionStore(app_paths),
        cdp_factory=lambda host, port: cdp,
        harness_factory=lambda paths: harness,
        browser_launcher=browser or FakeBrowserLauncher(),
        process_token=lambda pid: "linux:10",
        process_matches=lambda pid, token: owner_alive,
        monotonic=monotonic or (lambda: next(values)),
        sleep=sleep,
        stdout=stdout or io.StringIO(),
        stderr=stderr or io.StringIO(),
        install_signal_handlers=False,
    )


def options(proxy=None):
    return StartOptions(
        proxy=proxy,
        profile=None,
        headless=False,
        humanize=False,
        backend="playwright",
    )


def test_start_happy_path_closes_browser_daemon_and_session(app_paths):
    store = RecordingStore(app_paths)
    cdp = SequenceCdp([stopped_snapshot(), stopped_snapshot()])
    harness = FakeHarness(alive_states=[HarnessState(False, None)])
    browser = FakeBrowserLauncher()
    runtime = make_runtime(app_paths, cdp, harness, browser=browser, store=store)
    runtime._wait_for_shutdown = lambda session, client: 0
    assert runtime.start(options("http://user:pass@proxy.example:8080")) == 0
    assert browser.handle.closed is True
    assert len(harness.start_calls) == 1
    assert len(harness.stop_calls) == 1
    assert [record.phase for record in store.writes] == [
        "starting",
        "starting",
        "running",
    ]
    assert store.load().record is None
    assert any(
        item.proxy_endpoint == "http://proxy.example:8080" for item in store.writes
    )
    assert all("user:pass" not in str(item.to_dict()) for item in store.writes)


def test_deprecated_patchright_flag_uses_playwright(app_paths):
    store = RecordingStore(app_paths)
    cdp = SequenceCdp([stopped_snapshot(), stopped_snapshot()])
    harness = FakeHarness(alive_states=[HarnessState(False, None)])
    browser = FakeBrowserLauncher()
    runtime = make_runtime(app_paths, cdp, harness, browser=browser, store=store)
    runtime._wait_for_shutdown = lambda session, client: 0
    legacy_options = options()
    legacy_options = StartOptions(
        proxy=legacy_options.proxy,
        profile=legacy_options.profile,
        headless=legacy_options.headless,
        humanize=legacy_options.humanize,
        backend="patchright",
    )

    assert runtime.start(legacy_options) == 0
    assert browser.launch_options[0].__dict__ == {
        "cdp_port": 9333,
        "proxy": None,
        "profile": None,
        "headless": False,
        "humanize": False,
    }
    assert store.writes[0].backend == "playwright"
    assert "--backend patchright is deprecated" in runtime.stderr.getvalue()


def test_start_refuses_foreign_cdp_listener(app_paths):
    cdp = SequenceCdp([running_snapshot(owned=None, browser_id="foreign")])
    harness = FakeHarness()
    browser = FakeBrowserLauncher()
    runtime = make_runtime(app_paths, cdp, harness, browser=browser)
    assert runtime.start(options()) == 1
    assert browser.ensure_calls == 0
    assert "already in use" in runtime.stderr.getvalue()


def test_daemon_start_failure_closes_browser_and_clears_state(app_paths):
    cdp = SequenceCdp([stopped_snapshot(), stopped_snapshot()])
    harness = FakeHarness(
        start_result=HarnessResult(False, "log tail"),
        alive_states=[HarnessState(False, None)],
    )
    browser = FakeBrowserLauncher()
    runtime = make_runtime(app_paths, cdp, harness, browser=browser)
    assert runtime.start(options()) == 1
    assert browser.handle.closed is True
    assert SessionStore(app_paths).load().record is None
    assert "log tail" in runtime.stderr.getvalue()


def test_start_interruption_still_runs_owned_shutdown(app_paths):
    cdp = SequenceCdp([stopped_snapshot(), stopped_snapshot()])
    harness = FakeHarness(alive_states=[HarnessState(False, None)])
    browser = FakeBrowserLauncher()
    runtime = make_runtime(app_paths, cdp, harness, browser=browser)
    runtime._wait_for_shutdown = lambda session, client: 130
    assert runtime.start(options()) == 130
    assert browser.handle.closed is True
    assert harness.stop_calls


def test_stale_orphaned_browser_is_never_signalled(
    app_paths, session_record, monkeypatch
):
    store = SessionStore(app_paths)
    store.write(session_record)
    cdp = SequenceCdp([running_snapshot()])
    harness = FakeHarness(
        alive_states=[HarnessState(True, None)],
    )
    runtime = make_runtime(
        app_paths,
        cdp,
        harness,
        store=store,
        owner_alive=False,
    )
    monkeypatch.setattr(
        "os.kill", lambda *args: (_ for _ in ()).throw(AssertionError())
    )
    assert runtime._recover_stale_session(session_record) is False
    current = store.load().record
    assert current.phase == "orphaned"
    assert harness.stop_calls == [session_record]
    assert "did not signal a PID" in runtime.stderr.getvalue()


def test_stale_daemon_without_browser_is_cleaned(app_paths, session_record):
    store = SessionStore(app_paths)
    store.write(session_record)
    cdp = SequenceCdp([stopped_snapshot()])
    harness = FakeHarness(alive_states=[HarnessState(True, None)])
    runtime = make_runtime(
        app_paths,
        cdp,
        harness,
        store=store,
        owner_alive=False,
    )
    assert runtime._recover_stale_session(session_record) is True
    assert store.load().record is None
    assert harness.stop_calls == [session_record]


def test_stop_request_is_acknowledged_by_live_owner(app_paths, session_record):
    store = RecordingStore(app_paths)
    store.write(session_record)
    request_seen = []

    def sleep(_):
        request_seen.append(store.stop_requested(session_record.session_id))
        store.clear(session_record.session_id)

    runtime = make_runtime(
        app_paths,
        SequenceCdp([stopped_snapshot()]),
        FakeHarness(),
        store=store,
        owner_alive=True,
        sleep=sleep,
        monotonic=iter([0.0, 0.1, 0.2]).__next__,
    )
    assert runtime.stop(wait_timeout=1) == 0
    assert request_seen == [True]
    assert len(store.stop_requests) == 1


def test_stop_owner_gone_leaves_owned_browser_for_manual_cleanup(
    app_paths, session_record
):
    store = SessionStore(app_paths)
    store.write(session_record)
    harness = FakeHarness(alive_states=[HarnessState(True, None)])
    runtime = make_runtime(
        app_paths,
        SequenceCdp([running_snapshot()]),
        harness,
        store=store,
        owner_alive=False,
    )
    assert runtime.stop() == 1
    assert harness.stop_calls == [session_record]
    assert store.load().record.phase == "orphaned"
    assert "no PID was signalled" in runtime.stderr.getvalue()


def test_stop_owner_gone_cleans_daemon_when_browser_is_absent(
    app_paths, session_record
):
    store = SessionStore(app_paths)
    store.write(session_record)
    harness = FakeHarness(alive_states=[HarnessState(True, None)])
    runtime = make_runtime(
        app_paths,
        SequenceCdp([stopped_snapshot()]),
        harness,
        store=store,
        owner_alive=False,
    )
    assert runtime.stop() == 0
    assert harness.stop_calls == [session_record]
    assert store.load().record is None


def test_cleanup_failure_preserves_stale_session_for_retry(app_paths, session_record):
    store = SessionStore(app_paths)
    store.write(session_record)
    harness = FakeHarness(alive_states=[HarnessState(False, None)])

    def fail_cleanup(session):
        raise PermissionError("bu.log remains locked")

    harness.cleanup = fail_cleanup
    runtime = make_runtime(
        app_paths,
        SequenceCdp([stopped_snapshot()]),
        harness,
        store=store,
        owner_alive=False,
    )

    assert runtime.stop() == 1
    assert store.load().record == session_record
    assert "bu.log remains locked" in runtime.stderr.getvalue()


def test_run_cannot_race_harness_startup(app_paths, session_record):
    starting = session_record.with_updates(phase="starting")
    store = SessionStore(app_paths)
    store.write(starting)
    cdp = SequenceCdp([running_snapshot()])
    harness = FakeHarness()
    runtime = make_runtime(
        app_paths,
        cdp,
        harness,
        store=store,
        owner_alive=True,
    )

    assert runtime.run("pass", None) == 1
    assert cdp.calls == []
    assert harness.start_calls == []
    assert harness.execute_calls == []
    assert "session is starting" in runtime.stderr.getvalue()


def test_run_restarts_daemon_and_propagates_execution(app_paths, session_record):
    store = SessionStore(app_paths)
    store.write(session_record)
    harness = FakeHarness(
        alive_states=[HarnessState(False, None)],
        execute_result=7,
    )
    runtime = make_runtime(
        app_paths,
        SequenceCdp([running_snapshot()]),
        harness,
        store=store,
        owner_alive=True,
    )
    assert runtime.run("raise SystemExit(7)", 3) == 7
    assert harness.start_calls
    assert harness.execute_calls[0][1:] == ("raise SystemExit(7)", 3)


def test_run_timeout_is_real_subprocess_timeout_contract(app_paths, session_record):
    store = SessionStore(app_paths)
    store.write(session_record)
    harness = FakeHarness(
        alive_states=[HarnessState(True, None)],
        execute_result=124,
    )
    runtime = make_runtime(
        app_paths,
        SequenceCdp([running_snapshot()]),
        harness,
        store=store,
        owner_alive=True,
    )
    assert runtime.run("while True: pass", 0.1) == 124
    assert "timed out after 0.1s" in runtime.stderr.getvalue()


def test_run_rejects_pid_reuse_even_when_browser_endpoint_matches(
    app_paths, session_record
):
    store = SessionStore(app_paths)
    store.write(session_record)
    harness = FakeHarness()
    runtime = make_runtime(
        app_paths,
        SequenceCdp([running_snapshot()]),
        harness,
        store=store,
        owner_alive=False,
    )
    assert runtime.run("pass", None) == 1
    assert harness.execute_calls == []
    assert "owner is not running" in runtime.stderr.getvalue()


def test_wait_loop_honours_cross_platform_stop_request(app_paths, session_record):
    store = SessionStore(app_paths)
    store.write(session_record)
    store.request_stop(session_record.session_id, "2026-09-01T00:00:00Z")
    runtime = make_runtime(
        app_paths,
        SequenceCdp([running_snapshot()]),
        FakeHarness(),
        store=store,
        owner_alive=True,
    )
    assert (
        runtime._wait_for_shutdown(
            session_record,
            SequenceCdp([running_snapshot()]),
        )
        == 0
    )
    assert store.load().record.phase == "stopping"
