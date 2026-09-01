from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_metadata_is_consistent():
    module = load_script("check_release")
    assert module.package_version() == "0.2.1"
    assert module.validate() == []


def test_release_tag_requires_matching_tag_and_dated_changelog():
    module = load_script("check_release")
    errors = module.validate("v0.2.0")
    assert any("does not match" in error for error in errors)
    errors = module.validate("v0.2.1")
    assert any("must date" in error for error in errors)
