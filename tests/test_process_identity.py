from __future__ import annotations

import os
import subprocess

from cloak_browse.process_identity import process_start_token, same_process


def test_current_process_has_stable_identity():
    token = process_start_token(os.getpid())
    assert token is not None
    assert same_process(os.getpid(), token) is True
    assert same_process(os.getpid(), f"{token}-reused") is False


def test_invalid_process_ids_are_rejected():
    for pid in (True, 0, -1, 1 << 31):
        assert process_start_token(pid) is None


def test_darwin_identity_uses_process_start_time():
    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, b"Mon Sep  1 10:00:00 2026\n")

    assert process_start_token(42, platform_name="darwin", run=runner) == (
        "darwin:Mon Sep  1 10:00:00 2026"
    )


def test_darwin_identity_rejects_failed_lookup():
    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, b"")

    assert process_start_token(42, platform_name="darwin", run=runner) is None


def test_unknown_platform_is_not_assumed_safe():
    assert process_start_token(42, platform_name="unknown") is None
