from __future__ import annotations

import pytest

from cloak_browse.security import redact_proxy


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        ("http://user:pass@proxy.example:8080", "http://proxy.example:8080"),
        (
            "socks5://proxy.example:1080/path?token=secret",
            "socks5://proxy.example:1080",
        ),
        ("user:pass@proxy.example:9000", "proxy.example:9000"),
        ("http://[::1]:8080", "http://[::1]:8080"),
        ("not a proxy", "<configured>"),
    ],
)
def test_proxy_redaction(value, expected):
    assert redact_proxy(value) == expected
