from __future__ import annotations

from urllib.parse import urlsplit


def redact_proxy(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if not candidate or any(character.isspace() for character in candidate):
        return "<configured>"
    parsed = urlsplit(candidate if "://" in candidate else f"//{candidate}")
    try:
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return "<configured>"
    if not host:
        return "<configured>"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    endpoint = f"{host}:{port}" if port is not None else host
    return f"{parsed.scheme}://{endpoint}" if parsed.scheme else endpoint
