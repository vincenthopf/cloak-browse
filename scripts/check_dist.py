from __future__ import annotations

import argparse
import email
import sys
import tarfile
import zipfile
from pathlib import Path

from check_release import package_version

EXPECTED_DEPENDENCIES = {
    "browser-harness==0.1.10",
    "cloakbrowser==0.5.10",
    "platformdirs==4.11.7",
    "playwright==1.62.0",
    "websockets==15.0.1",
}
REQUIRED_SDIST_PATHS = {
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    "CHANGELOG.md",
    "LICENSE",
    "README.md",
    "SKILL.md",
    "cloak_browse/cli.py",
    "findings.md",
    "pyproject.toml",
    "scripts/check_dist.py",
    "scripts/check_release.py",
    "tests/test_cli.py",
    "uv.lock",
}
FORBIDDEN_PARTS = {".working", ".pytest_cache", "__pycache__", ".venv"}


def validate(dist: Path) -> list[str]:
    version = package_version()
    wheel = dist / f"cloak_browse-{version}-py3-none-any.whl"
    sdist = dist / f"cloak_browse-{version}.tar.gz"
    errors: list[str] = []
    if not wheel.is_file():
        errors.append(f"missing wheel {wheel.name}")
    if not sdist.is_file():
        errors.append(f"missing sdist {sdist.name}")
    ignored = {dist / ".gitignore"}
    extras = sorted(
        path.name for path in dist.iterdir() if path not in {wheel, sdist, *ignored}
    )
    if extras:
        errors.append(f"unexpected distribution files: {', '.join(extras)}")
    if wheel.is_file():
        errors.extend(_validate_wheel(wheel, version))
    if sdist.is_file():
        errors.extend(_validate_sdist(sdist, version))
    return errors


def _validate_wheel(path: Path, version: str) -> list[str]:
    errors: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        metadata_name = f"cloak_browse-{version}.dist-info/METADATA"
        entry_name = f"cloak_browse-{version}.dist-info/entry_points.txt"
        required = {"cloak_browse/cli.py", metadata_name, entry_name}
        missing = sorted(required - names)
        if missing:
            errors.append(f"wheel is missing: {', '.join(missing)}")
        if _forbidden(names):
            errors.append("wheel contains cache or working files")
        if metadata_name in names:
            message = email.message_from_bytes(archive.read(metadata_name))
            dependencies = set(message.get_all("Requires-Dist", []))
            if dependencies != EXPECTED_DEPENDENCIES:
                expected = sorted(EXPECTED_DEPENDENCIES)
                actual = sorted(dependencies)
                errors.append(
                    f"wheel dependencies differ: expected {expected}, got {actual}"
                )
        if entry_name in names:
            entries = archive.read(entry_name).decode("utf-8")
            if "cloak-browse = cloak_browse.cli:main" not in entries:
                errors.append("wheel entry point is incorrect")
    return errors


def _validate_sdist(path: Path, version: str) -> list[str]:
    errors: list[str] = []
    prefix = f"cloak_browse-{version}/"
    with tarfile.open(path, "r:gz") as archive:
        names = {member.name for member in archive.getmembers()}
    relative = {name.removeprefix(prefix) for name in names if name.startswith(prefix)}
    missing = sorted(REQUIRED_SDIST_PATHS - relative)
    if missing:
        errors.append(f"sdist is missing: {', '.join(missing)}")
    if _forbidden(relative):
        errors.append("sdist contains cache or working files")
    return errors


def _forbidden(names: set[str]) -> bool:
    return any(FORBIDDEN_PARTS.intersection(Path(name).parts) for name in names)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist", nargs="?", default="dist")
    args = parser.parse_args(argv)
    try:
        errors = validate(Path(args.dist))
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f"distribution check failed: {exc}", file=sys.stderr)
        return 1
    for error in errors:
        print(f"distribution check failed: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
