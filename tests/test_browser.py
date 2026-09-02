from __future__ import annotations

from pathlib import Path

import cloakbrowser

from cloak_browse.browser import BrowserLauncher, BrowserOptions


class Resource:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def options(profile: str | None = None) -> BrowserOptions:
    return BrowserOptions(
        cdp_port=9333,
        proxy="http://user:pass@proxy.example:8080",
        profile=profile,
        headless=True,
        humanize=True,
    )


def test_ensure_binary_uses_public_cloakbrowser_api(monkeypatch, tmp_path):
    binary = tmp_path / "cloak-chromium"
    monkeypatch.setattr(cloakbrowser, "ensure_binary", lambda: binary)

    assert BrowserLauncher().ensure_binary() == binary


def test_launch_uses_current_cloakbrowser_contract(monkeypatch):
    calls = []
    resource = Resource()

    def launch(**kwargs):
        calls.append(kwargs)
        return resource

    monkeypatch.setattr(cloakbrowser, "launch", launch)
    handle = BrowserLauncher().launch(options())

    assert calls == [
        {
            "headless": True,
            "proxy": "http://user:pass@proxy.example:8080",
            "args": [
                "--remote-debugging-address=127.0.0.1",
                "--remote-debugging-port=9333",
            ],
            "humanize": True,
        }
    ]
    assert "backend" not in calls[0]
    handle.close()
    assert resource.closed is True


def test_persistent_launch_expands_profile(monkeypatch, tmp_path):
    calls = []
    resource = Resource()

    def launch_persistent_context(**kwargs):
        calls.append(kwargs)
        return resource

    monkeypatch.setattr(
        cloakbrowser,
        "launch_persistent_context",
        launch_persistent_context,
    )
    profile = tmp_path / "profile"
    handle = BrowserLauncher().launch(options(str(profile)))

    assert Path(calls[0].pop("user_data_dir")) == profile
    assert "backend" not in calls[0]
    handle.close()
    assert resource.closed is True
