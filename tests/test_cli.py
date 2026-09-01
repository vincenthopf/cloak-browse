from __future__ import annotations

import pytest

from cloak_browse.cli import main


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def start(self, options):
        self.calls.append(("start", options))
        return 11

    def run(self, code, timeout):
        self.calls.append(("run", code, timeout))
        return 12

    def stop(self):
        self.calls.append(("stop",))
        return 13

    def status(self, json_output):
        self.calls.append(("status", json_output))
        return 14


def factory_for(runtime):
    return lambda: runtime


def test_no_command_prints_help_and_returns_usage(capsys):
    runtime = FakeRuntime()
    assert main([], factory_for(runtime)) == 2
    captured = capsys.readouterr()
    assert captured.out.startswith("usage: cloak-browse")
    assert captured.err == ""
    assert runtime.calls == []


def test_start_parser_preserves_cli_defaults():
    runtime = FakeRuntime()
    result = main(["start"], factory_for(runtime))
    assert result == 11
    name, options = runtime.calls[0]
    assert name == "start"
    assert options.backend == "patchright"
    assert options.headless is False
    assert options.humanize is False
    assert options.proxy is None
    assert options.profile is None


def test_start_parser_passes_all_options():
    runtime = FakeRuntime()
    result = main(
        [
            "start",
            "--proxy",
            "http://u:p@proxy:8000",
            "--profile",
            "~/profile",
            "--headless",
            "--humanize",
            "--backend",
            "playwright",
        ],
        factory_for(runtime),
    )
    assert result == 11
    options = runtime.calls[0][1]
    assert options.proxy == "http://u:p@proxy:8000"
    assert options.profile == "~/profile"
    assert options.headless is True
    assert options.humanize is True
    assert options.backend == "playwright"


def test_run_parser_and_exit_code():
    runtime = FakeRuntime()
    assert main(["run", "print(1)", "--timeout", "2.5"], factory_for(runtime)) == 12
    assert runtime.calls == [("run", "print(1)", 2.5)]


def test_timeout_must_be_positive(capsys):
    with pytest.raises(SystemExit) as raised:
        main(["run", "pass", "--timeout", "0"])
    assert raised.value.code == 2
    assert "timeout must be greater than zero" in capsys.readouterr().err


def test_stop_and_status_exit_codes():
    runtime = FakeRuntime()
    assert main(["stop"], factory_for(runtime)) == 13
    assert main(["status", "--json"], factory_for(runtime)) == 14
    assert runtime.calls == [("stop",), ("status", True)]


def test_version_is_available(capsys):
    with pytest.raises(SystemExit) as raised:
        main(["--version"])
    assert raised.value.code == 0
    assert capsys.readouterr().out.strip() == "cloak-browse 0.2.1"
