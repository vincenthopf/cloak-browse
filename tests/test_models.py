from __future__ import annotations

import pytest

from cloak_browse.models import SessionRecord


def test_session_round_trip(session_record):
    assert SessionRecord.from_dict(session_record.to_dict()) == session_record


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("schema_version", 2, "unsupported session schema"),
        ("owner_pid", True, "owner_pid must be an integer"),
        ("owner_pid", -1, "owner_pid is outside"),
        ("cdp_host", "0.0.0.0", "cdp_host must be"),
        ("cdp_port", 70000, "cdp_port is outside"),
        ("daemon_name", "../cloak", "daemon_name contains"),
        ("backend", "other", "unsupported backend"),
    ],
)
def test_session_validation_rejects_unsafe_values(session_record, key, value, message):
    data = session_record.to_dict()
    data[key] = value
    with pytest.raises(ValueError, match=message):
        SessionRecord.from_dict(data)


def test_legacy_patchright_session_remains_readable(session_record):
    data = session_record.to_dict()
    data["backend"] = "patchright"
    assert SessionRecord.from_dict(data).backend == "patchright"


def test_session_requires_complete_record(session_record):
    data = session_record.to_dict()
    del data["owner_started"]
    with pytest.raises(ValueError, match="owner_started must be a string"):
        SessionRecord.from_dict(data)
