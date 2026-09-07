import json

import pytest

from cloak_browse.computer_cli import action_code, human_approval, main, run_session


def test_action_code_encodes_input_without_code_injection():
    code = action_code("state", {"app": 'Calculator"); bad(); // '})
    assert 'sky.get_app_state({"app": "Calculator\\"); bad(); // "})' in code


@pytest.mark.parametrize(
    "operation,payload",
    [
        ("unknown", {"app": "Calculator"}),
        ("click", {"app": "Calculator"}),
        ("state", {"app": ""}),
        ("state", {"app": "Calculator", "bad": True}),
        ("state", {"app": "Calculator", "disableDiff": "yes"}),
        ("click", {"app": "Calculator", "element_index": True}),
        ("click", {"app": "Calculator", "x": float("nan"), "y": 2}),
    ],
)
def test_invalid_boundary_values(operation, payload):
    with pytest.raises(ValueError):
        action_code(operation, payload)


def test_tools_does_not_start_codex(capsys):
    assert main(["tools"]) == 0
    assert "state" in json.loads(capsys.readouterr().out)["operations"]


def test_approval_is_not_automatically_accepted():
    assert human_approval({"method": "unexpected"})["action"] == "decline"


class Client:
    def __init__(self):
        self.calls = []

    def execute(self, code, **kwargs):
        self.calls.append(code)
        return {"content": [], "isError": False}


def test_session_requires_state_and_acknowledgement(monkeypatch, capsys):
    import io

    values = [
        {
            "id": 1,
            "operation": "click",
            "args": {"app": "Calculator", "element_index": 2},
            "acknowledge_side_effects": True,
        },
        {"id": 2, "operation": "state", "args": {"app": "Calculator"}},
        {
            "id": 3,
            "operation": "click",
            "args": {"app": "Calculator", "element_index": 2},
        },
        {
            "id": 4,
            "operation": "click",
            "args": {"app": "Calculator", "element_index": 2},
            "acknowledge_side_effects": True,
        },
        {
            "id": 5,
            "operation": "click",
            "args": {"app": "Calculator", "element_index": 2},
            "acknowledge_side_effects": True,
        },
    ]
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(map(json.dumps, values))))
    client = Client()
    run_session(client, 10)
    results = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r["ok"] for r in results] == [False, True, False, True, False]
    assert len(client.calls) == 2
