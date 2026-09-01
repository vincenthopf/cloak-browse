from __future__ import annotations

import inspect
import os
from importlib import metadata

import pytest

EXPECTED_VERSIONS = {
    "browser-harness": "0.1.10",
    "cloakbrowser": "0.3.25",
    "patchright": "1.58.2",
    "platformdirs": "4.11.3",
    "playwright": "1.58.0",
    "websockets": "15.0.1",
}
EXPECTED_HELPERS = {
    "capture_screenshot",
    "click_at_xy",
    "fill_input",
    "goto_url",
    "js",
    "list_tabs",
    "new_tab",
    "page_info",
    "press_key",
    "switch_tab",
    "type_text",
    "visible_text",
    "wait_for_element",
    "wait_for_load",
}


def installed_version(name: str) -> str:
    if os.environ.get("CLOAK_BROWSE_VERIFY_DEPS") != "1":
        pytest.skip("dependency contracts require the project environment")
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        pytest.fail(f"{name} is missing from the project environment")


@pytest.mark.parametrize(("name", "version"), EXPECTED_VERSIONS.items())
def test_runtime_dependency_versions(name, version):
    assert installed_version(name) == version


def test_browser_harness_helper_contract():
    installed_version("browser-harness")
    import browser_harness.helpers as helpers

    assert EXPECTED_HELPERS <= set(dir(helpers))
    assert "Input.insertText" in inspect.getsource(helpers.type_text)


def test_cloakbrowser_backend_contract():
    installed_version("cloakbrowser")
    from cloakbrowser import launch, launch_persistent_context

    assert "backend" in inspect.signature(launch).parameters
    assert "backend" in inspect.signature(launch_persistent_context).parameters
