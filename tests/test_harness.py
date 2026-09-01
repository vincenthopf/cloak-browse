from __future__ import annotations

import subprocess

from cloak_browse.harness import HarnessManager


class Runner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def completed(code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


def test_alive_uses_isolated_session_environment(app_paths, session_record):
    runner = Runner([completed(0)])
    manager = HarnessManager(app_paths, runner=runner, environment={})
    state = manager.alive(session_record)
    assert state.alive is True
    env = runner.calls[0][1]["env"]
    assert env["BU_NAME"] == "cloak"
    assert env["BU_CDP_URL"] == "http://127.0.0.1:9333"
    assert session_record.session_id in env["BH_RUNTIME_DIR"]
    assert session_record.session_id in env["BH_TMP_DIR"]


def test_alive_false_and_probe_error(app_paths, session_record):
    manager = HarnessManager(app_paths, runner=Runner([completed(3)]), environment={})
    assert manager.alive(session_record).alive is False
    manager = HarnessManager(
        app_paths,
        runner=Runner([completed(1, stderr="ImportError: broken")]),
        environment={},
    )
    state = manager.alive(session_record)
    assert state.alive is False
    assert "ImportError: broken" in state.error


def test_start_waits_for_verified_ping(app_paths, session_record):
    runner = Runner([completed(0), completed(0)])
    manager = HarnessManager(app_paths, runner=runner, environment={})
    assert manager.start(session_record).ok is True
    assert len(runner.calls) == 2


def test_start_failure_includes_daemon_log_tail(app_paths, session_record):
    log_dir = app_paths.harness(session_record.session_id).tmp_dir
    log_dir.mkdir(parents=True)
    (log_dir / "bu.log").write_text("first\nlast useful line\n", encoding="utf-8")
    manager = HarnessManager(
        app_paths,
        runner=Runner([completed(1, stderr="startup failed")]),
        environment={},
    )
    result = manager.start(session_record)
    assert result.ok is False
    assert "startup failed" in result.error
    assert "last useful line" in result.error


def test_start_timeout_is_bounded(app_paths, session_record):
    timeout = subprocess.TimeoutExpired(["python"], 1)
    manager = HarnessManager(app_paths, runner=Runner([timeout]), environment={})
    result = manager.start(session_record, timeout=1)
    assert result.ok is False
    assert "timed out" in result.error


def test_stop_delegates_to_verified_upstream_shutdown(app_paths, session_record):
    runner = Runner([completed(0)])
    manager = HarnessManager(app_paths, runner=runner, environment={})
    assert manager.stop(session_record).ok is True
    assert "restart_daemon" in runner.calls[0][0][-1]


def test_execute_propagates_exit_code(app_paths, session_record):
    runner = Runner([completed(7)])
    manager = HarnessManager(app_paths, runner=runner, environment={})
    assert manager.execute(session_record, "raise SystemExit(7)", None) == 7
    command, kwargs = runner.calls[0]
    assert command[-2:] == ["-m", "browser_harness.run"]
    assert kwargs["input"] == "raise SystemExit(7)"
    assert kwargs["env"]["BH_REQUIRE_EXISTING_DAEMON"] == "1"


def test_execute_timeout_returns_standard_timeout_code(app_paths, session_record):
    runner = Runner([subprocess.TimeoutExpired(["python"], 2)])
    manager = HarnessManager(app_paths, runner=runner, environment={})
    assert manager.execute(session_record, "while True: pass", 2) == 124


def test_cleanup_only_removes_session_scoped_directories(app_paths, session_record):
    manager = HarnessManager(app_paths, runner=Runner([]), environment={})
    harness_paths = app_paths.harness(session_record.session_id)
    for path in (harness_paths.runtime_dir, harness_paths.tmp_dir, harness_paths.config_dir):
        path.mkdir(parents=True, exist_ok=True)
        (path / "data").write_text("x", encoding="utf-8")
    unrelated = app_paths.cache_dir / "unrelated"
    unrelated.mkdir()
    manager.cleanup(session_record)
    assert not harness_paths.runtime_dir.exists()
    assert not harness_paths.tmp_dir.exists()
    assert not harness_paths.config_dir.exists()
    assert unrelated.exists()
