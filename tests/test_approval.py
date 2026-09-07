import subprocess
from types import SimpleNamespace

import pytest

from cloak_browse.approval import dialog_approval


def request():
    return {
        "method": "mcpServer/elicitation/request",
        "params": {
            "mode": "form",
            "message": 'Allow "Helium"?',
            "requestedSchema": {"properties": {}},
            "_meta": {
                "connector_id": "computer-use",
                "tool_name": "get_app_state",
                "tool_params": {"app": "net.imput.helium"},
            },
        },
    }


@pytest.mark.parametrize(
    "answer,code,expected",
    [
        ("Allow this session\n", 0, "accept"),
        ("deny\n", 0, "decline"),
        ("Allow this session", 1, "decline"),
        ("", 0, "decline"),
    ],
)
def test_dialog_requires_exact_human_result(monkeypatch, answer, code, expected):
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=code, stdout=answer),
    )
    assert dialog_approval(request())["action"] == expected


def test_unrelated_approval_never_opens_dialog(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: pytest.fail("unexpected dialog")
    )
    assert dialog_approval({})["action"] == "decline"


def test_timeout_declines(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")

    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired("osascript", 125)

    monkeypatch.setattr(subprocess, "run", run)
    assert dialog_approval(request())["action"] == "decline"
