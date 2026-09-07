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


def session_request(app="net.imput.helium", tool="get_app_state"):
    value = request()
    value["params"].update(threadId="thread", serverName="node_repl")
    value["params"]["_meta"].update(
        codex_approval_kind="mcp_tool_call",
        persist=["session"],
        riskLevel="low",
        tool_name=tool,
        tool_params={"app": app},
    )
    return value


def test_one_grant_covers_app_tools_only(monkeypatch):
    from cloak_browse.approval import SessionApproval

    prompts = []

    def allow(value):
        prompts.append(value)
        return {"action": "accept", "content": {}}

    monkeypatch.setattr("cloak_browse.approval.dialog_approval", allow)
    approval = SessionApproval()
    assert approval(session_request())["action"] == "accept"
    assert approval(session_request(tool="click"))["action"] == "accept"
    assert approval(session_request(tool="press_key"))["action"] == "accept"
    assert len(prompts) == 1
    approval(session_request(app="com.apple.calculator"))
    assert len(prompts) == 2
    SessionApproval()(session_request())
    assert len(prompts) == 3


def test_scope_change_requires_new_grant(monkeypatch):
    from cloak_browse.approval import SessionApproval

    prompts = []

    def allow(value):
        prompts.append(value)
        return {"action": "accept", "content": {}}

    monkeypatch.setattr("cloak_browse.approval.dialog_approval", allow)
    approval = SessionApproval()
    approval(session_request())
    changed = session_request()
    changed["params"]["threadId"] = "other"
    approval(changed)
    changed = session_request()
    changed["params"]["_meta"]["riskLevel"] = "high"
    approval(changed)
    assert len(prompts) == 3
    assert (
        approval(session_request(tool="start_audio_recording"))["action"] == "decline"
    )
    assert len(prompts) == 3


def test_decline_is_never_cached(monkeypatch):
    from cloak_browse.approval import SessionApproval

    monkeypatch.setattr(
        "cloak_browse.approval.dialog_approval",
        lambda r: {"action": "decline", "content": None},
    )
    approval = SessionApproval()
    approval(session_request())
    assert not approval.approved
