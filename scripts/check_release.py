from __future__ import annotations

import argparse
import re
import sys
import tomllib
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "cloak_browse" / "_version.py"
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"
README = ROOT / "README.md"


def package_version() -> str:
    match = re.fullmatch(
        r'__version__\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"\s*',
        VERSION_FILE.read_text(encoding="utf-8"),
    )
    if match is None:
        raise ValueError("cloak_browse/_version.py must contain one semantic version")
    return match.group(1)


def validate(tag: str | None = None) -> list[str]:
    errors: list[str] = []
    version = package_version()
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    dynamic = project.get("project", {}).get("dynamic", [])
    version_path = project.get("tool", {}).get("hatch", {}).get("version", {}).get("path")
    if "version" not in dynamic:
        errors.append("pyproject.toml must declare version as dynamic")
    if version_path != "cloak_browse/_version.py":
        errors.append("Hatch version path must be cloak_browse/_version.py")
    changelog = CHANGELOG.read_text(encoding="utf-8")
    if f"## [{version}] - " not in changelog:
        errors.append(f"CHANGELOG.md has no {version} release heading")
    readme = README.read_text(encoding="utf-8")
    if f"Current package version: `{version}`" not in readme:
        errors.append(f"README.md does not identify version {version}")
    if tag is not None:
        expected = f"v{version}"
        if tag != expected:
            errors.append(f"tag {tag!r} does not match package version {expected!r}")
        dated_heading = re.search(
            rf"^## \[{re.escape(version)}\] - (\d{{4}}-\d{{2}}-\d{{2}})$",
            changelog,
            re.MULTILINE,
        )
        if dated_heading is None:
            errors.append(f"CHANGELOG.md must date {version} before release")
        else:
            try:
                date.fromisoformat(dated_heading.group(1))
            except ValueError:
                errors.append(f"CHANGELOG.md has an invalid date for {version}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag")
    args = parser.parse_args(argv)
    try:
        errors = validate(args.tag)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"release check failed: {exc}", file=sys.stderr)
        return 1
    for error in errors:
        print(f"release check failed: {error}", file=sys.stderr)
    if errors:
        return 1
    print(f"release metadata is consistent for {package_version()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
