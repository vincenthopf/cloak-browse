from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit


@dataclass(frozen=True)
class TabInfo:
    title: str
    url: str


@dataclass(frozen=True)
class CdpSnapshot:
    listener: bool
    http_available: bool
    websocket_available: bool
    owned: bool | None
    browser_id: str | None
    browser_version: str | None
    tabs: tuple[TabInfo, ...] | None
    error: str | None


class CdpClient:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9333,
        opener: Callable[..., Any] = urllib.request.urlopen,
        websocket_connect: Callable[..., Any] | None = None,
        listener_probe: Callable[[str, int, float], bool] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.host = host
        self.port = port
        self.opener = opener
        self.websocket_connect = websocket_connect
        self.listener_probe = listener_probe or _listener_probe
        self.monotonic = monotonic
        self.sleep = sleep

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def probe(
        self,
        expected_browser_id: str | None = None,
        include_tabs: bool = True,
        timeout: float = 1.0,
    ) -> CdpSnapshot:
        listener = self.listener_probe(self.host, self.port, timeout)
        if not listener:
            return CdpSnapshot(False, False, False, None, None, None, None, None)
        version_value, version_error, version_responded = self._read_json(
            "/json/version", timeout
        )
        if not isinstance(version_value, dict):
            return CdpSnapshot(
                True,
                version_responded,
                False,
                False if expected_browser_id else None,
                None,
                None,
                None,
                version_error or "CDP version response is not an object",
            )
        websocket_url = version_value.get("webSocketDebuggerUrl")
        browser_id = (
            browser_id_from_websocket_url(websocket_url)
            if isinstance(websocket_url, str)
            else None
        )
        owned = None if expected_browser_id is None else browser_id == expected_browser_id
        websocket_available, websocket_error = self._probe_websocket(
            websocket_url, timeout
        )
        tabs: tuple[TabInfo, ...] | None = None
        tabs_error = None
        if include_tabs:
            targets, targets_error, _ = self._read_json("/json/list", timeout)
            if isinstance(targets, list):
                tabs = tuple(
                    TabInfo(
                        title=str(item.get("title") or ""),
                        url=str(item.get("url") or ""),
                    )
                    for item in targets
                    if isinstance(item, dict) and item.get("type") == "page"
                )
            else:
                tabs_error = targets_error or "CDP target response is not an array"
        errors = [item for item in (version_error, websocket_error, tabs_error) if item]
        return CdpSnapshot(
            listener=True,
            http_available=True,
            websocket_available=websocket_available,
            owned=owned,
            browser_id=browser_id,
            browser_version=_optional_string(version_value.get("Browser")),
            tabs=tabs,
            error="; ".join(errors) if errors else None,
        )

    def wait_ready(
        self,
        timeout: float,
        interval: float = 0.2,
    ) -> CdpSnapshot:
        deadline = self.monotonic() + timeout
        last = CdpSnapshot(False, False, False, None, None, None, None, None)
        while self.monotonic() < deadline:
            last = self.probe(include_tabs=False)
            if last.websocket_available and last.browser_id:
                return last
            self.sleep(interval)
        return last

    def _read_json(self, path: str, timeout: float) -> tuple[Any, str | None, bool]:
        try:
            with self.opener(f"{self.base_url}{path}", timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            return None, f"CDP HTTP {exc.code} for {path}", True
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return None, f"CDP request failed for {path}: {_brief_error(exc)}", False
        try:
            return json.loads(raw), None, True
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return None, f"CDP returned malformed JSON for {path}: {exc}", True

    def _probe_websocket(
        self,
        websocket_url: Any,
        timeout: float,
    ) -> tuple[bool, str | None]:
        if not isinstance(websocket_url, str) or not websocket_url:
            return False, "CDP response has no WebSocket URL"
        connect = self.websocket_connect
        if connect is None:
            from websockets.sync.client import connect as connect_websocket

            connect = connect_websocket
        connection = None
        try:
            connection = connect(
                websocket_url,
                open_timeout=timeout,
                close_timeout=min(timeout, 1.0),
            )
            return True, None
        except Exception as exc:
            return False, f"CDP WebSocket probe failed: {_brief_error(exc)}"
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass


def browser_id_from_websocket_url(value: str) -> str | None:
    path = urlsplit(value).path.rstrip("/")
    marker = "/devtools/browser/"
    if marker not in path:
        return None
    browser_id = path.rsplit(marker, 1)[-1]
    return browser_id or None


def _listener_probe(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, TimeoutError, OSError):
        return False


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _brief_error(error: BaseException) -> str:
    text = str(error).strip()
    return text[:240] if text else error.__class__.__name__
