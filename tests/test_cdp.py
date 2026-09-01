from __future__ import annotations

import io
import json
import urllib.error

from cloak_browse.cdp import (
    CdpClient,
    CdpSnapshot,
    TabInfo,
    browser_id_from_websocket_url,
)


class Response:
    def __init__(self, value):
        self.value = value if isinstance(value, bytes) else json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.value


class Connection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def client_with(version, targets=(), websocket_connect=None):
    def opener(url, timeout):
        if url.endswith("/json/version"):
            return Response(version)
        if url.endswith("/json/list"):
            return Response(targets)
        raise AssertionError(url)

    return CdpClient(
        opener=opener,
        websocket_connect=websocket_connect or (lambda *args, **kwargs: Connection()),
        listener_probe=lambda *args: True,
    )


def test_successful_http_websocket_and_target_probe():
    connection = Connection()
    client = client_with(
        {
            "Browser": "Chrome/145",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9333/devtools/browser/browser-1",
        },
        [
            {"type": "page", "title": "One", "url": "https://one.example"},
            {"type": "service_worker", "title": "Ignored", "url": "x"},
        ],
        websocket_connect=lambda *args, **kwargs: connection,
    )
    snapshot = client.probe(expected_browser_id="browser-1")
    assert snapshot == CdpSnapshot(
        listener=True,
        http_available=True,
        websocket_available=True,
        owned=True,
        browser_id="browser-1",
        browser_version="Chrome/145",
        tabs=(TabInfo("One", "https://one.example"),),
        error=None,
    )
    assert connection.closed is True


def test_no_listener_is_a_clean_stopped_state():
    client = CdpClient(listener_probe=lambda *args: False)
    assert client.probe() == CdpSnapshot(
        False, False, False, None, None, None, None, None
    )


def test_malformed_json_is_actionable():
    def opener(url, timeout):
        return Response(b"not-json")

    snapshot = CdpClient(
        opener=opener,
        listener_probe=lambda *args: True,
    ).probe(expected_browser_id="expected")
    assert snapshot.listener is True
    assert snapshot.http_available is True
    assert snapshot.websocket_available is False
    assert snapshot.owned is False
    assert "malformed JSON" in snapshot.error


def test_wrong_browser_identity_is_foreign():
    snapshot = client_with(
        {
            "Browser": "Chrome/145",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9333/devtools/browser/other",
        }
    ).probe(expected_browser_id="browser-1", include_tabs=False)
    assert snapshot.owned is False
    assert snapshot.browser_id == "other"


def test_http_error_distinguishes_listener_from_cdp():
    def opener(url, timeout):
        raise urllib.error.HTTPError(url, 404, "not found", {}, io.BytesIO())

    snapshot = CdpClient(
        opener=opener,
        listener_probe=lambda *args: True,
    ).probe()
    assert snapshot.listener is True
    assert snapshot.http_available is True
    assert "HTTP 404" in snapshot.error


def test_websocket_timeout_is_reported():
    def timeout(*args, **kwargs):
        raise TimeoutError("slow")

    snapshot = client_with(
        {
            "Browser": "Chrome/145",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9333/devtools/browser/browser-1",
        },
        websocket_connect=timeout,
    ).probe(include_tabs=False)
    assert snapshot.websocket_available is False
    assert "WebSocket probe failed" in snapshot.error


def test_wait_ready_is_bounded():
    current = [0.0]
    attempts = []
    client = CdpClient(
        monotonic=lambda: current[0],
        sleep=lambda value: current.__setitem__(0, current[0] + value),
    )
    stopped = CdpSnapshot(False, False, False, None, None, None, None, None)

    def probe(*args, **kwargs):
        attempts.append(1)
        return stopped

    client.probe = probe
    assert client.wait_ready(timeout=0.5, interval=0.2) == stopped
    assert len(attempts) == 3


def test_browser_id_ignores_query_strings():
    assert (
        browser_id_from_websocket_url(
            "ws://localhost/devtools/browser/abc?token=secret"
        )
        == "abc"
    )
    assert browser_id_from_websocket_url("ws://localhost/devtools/page/abc") is None
