import inspect

import browser_harness.helpers as helpers


def harness_stubs(monkeypatch):
    calls = []

    def cdp(method, **kwargs):
        calls.append((method, kwargs))
        if method == "Target.attachToTarget":
            return {"sessionId": "session"}
        if method == "Target.createTarget":
            return {"targetId": "new"}
        return {}

    monkeypatch.setattr(helpers, "cdp", cdp)
    monkeypatch.setattr(helpers, "_send", lambda value: {})
    monkeypatch.setattr(helpers, "_mark_tab", lambda: None)
    return calls


def test_switch_tab_attaches_without_activation(monkeypatch):
    calls = harness_stubs(monkeypatch)
    helpers.switch_tab("target")
    assert "Target.attachToTarget" in [method for method, _ in calls]
    assert "Target.activateTarget" not in [method for method, _ in calls]
    assert "Page.bringToFront" not in [method for method, _ in calls]


def test_explicit_activation_remains_available(monkeypatch):
    calls = harness_stubs(monkeypatch)
    helpers.switch_tab("target", activate=True)
    assert ("Target.activateTarget", {"targetId": "target"}) in calls


def test_new_tab_requests_background_creation(monkeypatch):
    calls = harness_stubs(monkeypatch)
    helpers.new_tab()
    assert ("Target.createTarget", {"url": "about:blank", "background": True}) in calls
    assert "Target.activateTarget" not in [method for method, _ in calls]


def test_daemon_fallback_targets_are_background():
    import ast

    from browser_harness import daemon

    tree = ast.parse(inspect.getsource(daemon))
    found = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        if not isinstance(node.args[0], ast.Constant):
            continue
        if node.args[0].value != "Target.createTarget":
            continue
        value = ast.literal_eval(node.args[1])
        assert value["background"] is True
        found += 1
    assert found >= 2
