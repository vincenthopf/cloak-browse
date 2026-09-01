from __future__ import annotations

import json
import os

from cloak_browse.session import SessionStore


def test_missing_session_is_normal(app_paths):
    assert SessionStore(app_paths).load().record is None
    assert SessionStore(app_paths).load().error is None


def test_corrupt_and_partial_sessions_are_reported(app_paths, session_record):
    app_paths.session_file.write_text("{", encoding="utf-8")
    assert "invalid session file" in SessionStore(app_paths).load().error
    app_paths.session_file.write_text(
        json.dumps({"schema_version": 1}), encoding="utf-8"
    )
    assert "session_id must be a string" in SessionStore(app_paths).load().error
    app_paths.session_file.write_text(
        json.dumps(session_record.to_dict()), encoding="utf-8"
    )
    assert SessionStore(app_paths).load().record == session_record


def test_session_write_is_atomic_and_private(app_paths, session_record, monkeypatch):
    replacements = []
    real_replace = os.replace

    def record_replace(source, target):
        replacements.append((source, target))
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", record_replace)
    store = SessionStore(app_paths)
    store.write(session_record)
    assert len(replacements) == 1
    assert replacements[0][1] == app_paths.session_file
    assert store.load().record == session_record
    assert not list(app_paths.cache_dir.glob(".session.json.*.tmp"))
    if os.name != "nt":
        assert app_paths.session_file.stat().st_mode & 0o777 == 0o600
        assert app_paths.cache_dir.stat().st_mode & 0o777 == 0o700


def test_atomic_replacement_never_merges_old_fields(app_paths, session_record):
    store = SessionStore(app_paths)
    store.write(session_record)
    replacement = session_record.with_updates(phase="stopping", browser_version=None)
    store.write(replacement)
    raw = json.loads(app_paths.session_file.read_text(encoding="utf-8"))
    assert raw == replacement.to_dict()


def test_clear_checks_session_identity(app_paths, session_record):
    store = SessionStore(app_paths)
    store.write(session_record)
    assert store.clear("different") is False
    assert app_paths.session_file.exists()
    assert store.clear(session_record.session_id) is True
    assert not app_paths.session_file.exists()


def test_stop_request_is_scoped_to_session(app_paths, session_record):
    store = SessionStore(app_paths)
    store.request_stop(session_record.session_id, "2026-09-01T00:00:00Z")
    assert store.stop_requested(session_record.session_id) is True
    assert store.stop_requested("different") is False
    assert store.clear_stop("different") is False
    assert store.clear_stop(session_record.session_id) is True


def test_corrupt_session_can_be_quarantined(app_paths):
    app_paths.session_file.parent.mkdir(parents=True, exist_ok=True)
    app_paths.session_file.write_text("broken", encoding="utf-8")
    store = SessionStore(app_paths, now=lambda: 0)
    target = store.quarantine()
    assert target is not None
    assert target.name == "session.corrupt.19700101T000000Z.json"
    assert target.read_text(encoding="utf-8") == "broken"
    assert not app_paths.session_file.exists()
